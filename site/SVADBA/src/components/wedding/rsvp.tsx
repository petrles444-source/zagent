"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { wedding } from "@/lib/wedding-config";
import { Heart, SectionHeading } from "./ornaments";
import { Reveal } from "./reveal";
import { ConfettiBurst } from "./confetti-burst";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type FormValues = {
  name: string;
  email?: string;
  phone?: string;
  attending: "yes" | "no" | "maybe";
  guests: number;
  meal: "regular" | "vegetarian" | "vegan" | "kids";
  drink: "wine" | "champagne" | "strong" | "none";
  message?: string;
};

type Stats = {
  yes: number;
  no: number;
  maybe: number;
  totalGuests: number;
  responses: number;
} | null;

export function Rsvp() {
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState<Stats>(null);
  const [done, setDone] = useState(false);

  const { register, handleSubmit, watch, reset, formState: { errors } } = useForm<FormValues>({
    defaultValues: {
      name: "",
      email: "",
      phone: "",
      attending: "yes",
      guests: 1,
      meal: "regular",
      drink: "wine",
      message: "",
    },
  });

  const attending = watch("attending");

  const loadStats = async () => {
    try {
      const res = await fetch("/api/rsvp", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setStats(data.stats ?? null);
      }
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const res = await fetch("/api/rsvp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({
          title: "Не получилось",
          description: data?.error ?? "Попробуйте ещё раз чуть позже.",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Спасибо!",
          description:
            values.attending === "no"
              ? "Будем скучать. Спасибо, что сообщили."
              : "Ваш ответ сохранён. До встречи в полночь!",
        });
        setDone(true);
        reset();
        loadStats();
      }
    } catch {
      toast({
        title: "Ошибка сети",
        description: "Проверьте соединение и попробуйте снова.",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      id="rsvp"
      className="relative overflow-hidden bg-night py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-[0.10]"
        style={{ backgroundImage: "url(/wedding/rings.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-5xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Подтверждение визита"
            title="Будете ли вы с нами"
            subtitle="Пожалуйста, заполните форму до 1 октября 2026 года. Это поможет нам учесть предпочтения по меню и напиткам."
          />
        </Reveal>

        {/* Live stats */}
        <Reveal delay={120} className="mt-12">
          <div className="mx-auto grid max-w-3xl grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Подтвердили" value={stats?.yes ?? "—"} accent />
            <Stat label="Всего гостей" value={stats?.totalGuests ?? "—"} />
            <Stat label="Сомневаются" value={stats?.maybe ?? "—"} />
            <Stat label="Ответов" value={stats?.responses ?? "—"} />
          </div>
        </Reveal>

        {/* Guest count goal progress bar */}
        <Reveal delay={150} className="mt-8">
          <GuestGoalBar
            confirmed={stats?.totalGuests ?? 0}
            goal={120}
            responses={stats?.responses ?? 0}
          />
        </Reveal>

        <Reveal delay={180} className="mt-12">
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="card-luxe relative overflow-hidden rounded-sm p-6 sm:p-10"
          >
            <span className="pointer-events-none absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />

            {done ? (
              <div className="flex flex-col items-center gap-4 py-12 text-center">
                <Heart className="h-8 w-8 text-gold animate-flicker" filled />
                <p className="font-script text-4xl text-gold-soft">Благодарим вас</p>
                <p className="max-w-md font-cormorant text-lg text-ivory-soft/80">
                  Ваш ответ получен. Мы напишем вам накануне торжества, чтобы
                  подтвердить все детали. До встречи под звёздами!
                </p>
                <button
                  type="button"
                  onClick={() => setDone(false)}
                  className="btn-ghost-luxe mt-2"
                >
                  Отправить ещё ответ
                </button>
              </div>
            ) : (
              <div className="grid gap-6 md:grid-cols-2">
                <Field label="Ваше имя" required error={errors.name?.message}>
                  <input
                    className="input-luxe"
                    placeholder="Имя и фамилия"
                    {...register("name", { required: "Укажите имя" })}
                  />
                </Field>

                <Field label="Телефон">
                  <input
                    className="input-luxe"
                    placeholder="+7 (___) ___-__-__"
                    {...register("phone")}
                  />
                </Field>

                <Field label="E-mail">
                  <input
                    type="email"
                    className="input-luxe"
                    placeholder="you@example.com"
                    {...register("email")}
                  />
                </Field>

                <Field label="Количество гостей">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    className="input-luxe"
                    {...register("guests", { valueAsNumber: true })}
                  />
                </Field>

                <Field label="Сможете прийти?">
                  <div className="grid grid-cols-3 gap-2">
                    <Choice label="Да, буду" value="yes" {...register("attending")} />
                    <Choice label="Пока не уверен" value="maybe" {...register("attending")} />
                    <Choice label="К сожалению, нет" value="no" {...register("attending")} />
                  </div>
                </Field>

                {attending !== "no" && (
                  <>
                    <Field label="Предпочтения по меню">
                      <select className="input-luxe" {...register("meal")}>
                        <option value="regular">Основное меню</option>
                        <option value="vegetarian">Вегетарианское</option>
                        <option value="vegan">Веганское</option>
                        <option value="kids">Детское</option>
                      </select>
                    </Field>
                    <Field label="Напиток вечера">
                      <select className="input-luxe" {...register("drink")}>
                        <option value="wine">Вино</option>
                        <option value="champagne">Шампанское</option>
                        <option value="strong">Крепкие напитки</option>
                        <option value="none">Безалкогольные</option>
                      </select>
                    </Field>
                  </>
                )}

                <div className="md:col-span-2">
                  <Field label="Сообщение молодожёнам">
                    <textarea
                      rows={3}
                      className="input-luxe resize-none"
                      placeholder="Тёплые слова, пожелания, вопросы..."
                      {...register("message")}
                    />
                  </Field>
                </div>

                <div className="md:col-span-2 mt-2 flex flex-col items-center gap-3">
                  <div className="ornament-line text-gold">
                    <Heart className="h-3 w-3" />
                  </div>
                  <button type="submit" disabled={submitting} className="btn-luxe disabled:opacity-60">
                    {submitting ? "Отправляем…" : "Отправить ответ"}
                  </button>
                  <p className="font-cormorant text-sm text-ivory-soft/60">
                    До дедлайна RSVP — 1 октября 2026
                  </p>
                </div>
              </div>
            )}
          </form>
        </Reveal>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: number | string;
  accent?: boolean;
}) {
  return (
    <div className="card-luxe rounded-sm p-4 text-center">
      <div
        className={cn(
          "font-playfair text-4xl sm:text-5xl tabular-nums",
          accent ? "text-gold-gradient" : "text-ivory"
        )}
      >
        {value}
      </div>
      <div className="mt-1 font-playfair text-[0.64rem] uppercase tracking-luxe text-ivory-soft/70">
        {label}
      </div>
    </div>
  );
}

function Field({
  label,
  required,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
        {label}
        {required ? <span className="text-gold/70"> *</span> : null}
      </span>
      {children}
      {error ? (
        <span className="font-cormorant text-sm text-blush">{error}</span>
      ) : null}
    </label>
  );
}

function Choice({
  label,
  value,
  ...props
}: { label: string; value: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="group relative cursor-pointer">
      <input
        type="radio"
        value={value}
        className="peer sr-only"
        {...props}
      />
      <span
        className={cn(
          "block rounded-sm border border-gold/25 bg-night/40 px-3 py-2.5 text-center font-cormorant text-sm text-ivory-soft/80 transition-all",
          "peer-checked:border-gold peer-checked:bg-gold/15 peer-checked:text-ivory",
          "hover:border-gold/50"
        )}
      >
        {label}
      </span>
    </label>
  );
}

/** Progress bar showing confirmed guests against the wedding goal.
 *  Triggers a confetti burst the moment the goal is reached. */
function GuestGoalBar({
  confirmed,
  goal,
  responses,
}: {
  confirmed: number;
  goal: number;
  responses: number;
}) {
  const pct = Math.min(100, Math.round((confirmed / goal) * 100));
  const reached = confirmed >= goal && goal > 0;
  const [fireConfetti, setFireConfetti] = useState(false);
  const [seed, setSeed] = useState(0);
  const prevReached = useRef(false);

  useEffect(() => {
    // fire confetti once when the goal is first reached — deferred to rAF
    // so setState isn't synchronous in the effect body.
    const raf = requestAnimationFrame(() => {
      if (reached && !prevReached.current) {
        setSeed((s) => s + 1);
        setFireConfetti(true);
      }
      prevReached.current = reached;
    });
    return () => cancelAnimationFrame(raf);
  }, [reached]);

  return (
    <>
      <div className="card-luxe mx-auto max-w-3xl rounded-sm p-6">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
            {reached ? "🎉 Цель достигнута!" : `Наша цель — ${goal} гостей`}
          </span>
          <span className="font-playfair text-lg text-gold-gradient tabular-nums">
            {confirmed} / {goal}
          </span>
        </div>
        <div className="relative mt-3 h-3 overflow-hidden rounded-full bg-gold/10">
          <div
            className={cn(
              "h-full rounded-full bg-gradient-to-r transition-[width] duration-700 ease-out",
              reached
                ? "from-blush via-gold to-blush shadow-[0_0_14px_rgba(231,201,192,0.5)]"
                : "from-gold-soft via-gold to-gold-soft shadow-[0_0_10px_rgba(200,169,106,0.5)]"
            )}
            style={{ width: `${pct}%` }}
          />
          {/* shimmer overlay */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "linear-gradient(90deg, transparent, rgba(244,236,224,0.15), transparent)",
              backgroundSize: "200% 100%",
              animation: "glassShimmer 3s linear infinite",
            }}
            aria-hidden="true"
          />
        </div>
        <div className="mt-2 flex items-center justify-between font-cormorant text-xs text-ivory-soft/50">
          <span>{pct}% подтверждено</span>
          <span>{responses} ответов получено</span>
        </div>
      </div>
      {fireConfetti && (
        <ConfettiBurst fire={fireConfetti} seed={seed} key={seed} />
      )}
    </>
  );
}
