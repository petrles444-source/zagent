"use client";

import { useEffect, useMemo, useState } from "react";
import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type Lock = {
  id: string;
  initials: string;
  message: string | null;
  color: string;
  createdAt: string;
};

const COLORS = [
  { key: "gold", label: "Золото", hex: "#c8a96a", fg: "#0b0908" },
  { key: "blush", label: "Роза", hex: "#e7c9c0", fg: "#3d2a26" },
  { key: "ivory", label: "Слоновая кость", hex: "#f4ece0", fg: "#0b0908" },
  { key: "champagne", label: "Шампань", hex: "#e8dcc8", fg: "#0b0908" },
];

export function LoveLocks() {
  const { toast } = useToast();
  const [locks, setLocks] = useState<Lock[]>([]);
  const [loading, setLoading] = useState(true);
  const [initials, setInitials] = useState("");
  const [message, setMessage] = useState("");
  const [color, setColor] = useState("gold");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      const res = await fetch("/api/love-locks", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setLocks(data.items ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const clean = initials.trim().toUpperCase();
    if (clean.length < 2) {
      toast({ title: "Введите минимум 2 буквы", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/love-locks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initials: clean, message: message.trim() || undefined, color }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: data?.error, variant: "destructive" });
      } else {
        toast({ title: "Замок повешен!", description: "Ваша любовь теперь часть нашего моста." });
        setInitials("");
        setMessage("");
        await load();
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      id="love-locks"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Мост любви"
            title="Замки навсегда"
            subtitle="Повесьте свой замок на наш виртуальный мост — символ того, что ваша любовь, как и наша, теперь заперта навечно. Бросьте ключ в реку времени."
          />
        </Reveal>

        <div className="mt-14 grid gap-10 lg:grid-cols-[1fr_1.3fr]">
          {/* Form */}
          <Reveal>
            <form onSubmit={submit} className="card-luxe rounded-sm p-6 sm:p-8">
              <div className="flex flex-col gap-5">
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Ваши инициалы
                  </span>
                  <input
                    className="input-luxe text-center font-playfair text-2xl tracking-[0.3em] uppercase"
                    placeholder="А♥С"
                    value={initials}
                    maxLength={4}
                    onChange={(e) => setInitials(e.target.value)}
                    style={{ letterSpacing: "0.25em" }}
                  />
                  <span className="text-right font-cormorant text-xs text-ivory-soft/50">
                    {initials.length}/4
                  </span>
                </label>
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Послание (необязательно)
                  </span>
                  <textarea
                    rows={3}
                    className="input-luxe resize-none"
                    placeholder="Пара слов о вашей любви…"
                    value={message}
                    maxLength={120}
                    onChange={(e) => setMessage(e.target.value)}
                  />
                  <span className="text-right font-cormorant text-xs text-ivory-soft/50">
                    {message.length}/120
                  </span>
                </label>
                <div className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Цвет замка
                  </span>
                  <div className="grid grid-cols-4 gap-2">
                    {COLORS.map((c) => (
                      <button
                        key={c.key}
                        type="button"
                        onClick={() => setColor(c.key)}
                        className={cn(
                          "group flex flex-col items-center gap-1 rounded-sm border p-2 transition-all",
                          color === c.key
                            ? "border-gold ring-1 ring-gold/40"
                            : "border-gold/20 hover:border-gold/50"
                        )}
                        aria-label={c.label}
                      >
                        <span
                          className="h-8 w-8 rounded-full border border-gold/30 shadow-inner"
                          style={{ backgroundColor: c.hex }}
                        />
                        <span className="font-cormorant text-[0.7rem] text-ivory-soft/70">
                          {c.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col items-center gap-2">
                  <div className="ornament-line text-gold">
                    <Heart className="h-3 w-3" />
                  </div>
                  <button type="submit" disabled={submitting} className="btn-luxe disabled:opacity-60">
                    {submitting ? "Вешаем…" : "Повесить замок"}
                  </button>
                </div>
              </div>
            </form>
          </Reveal>

          {/* The bridge */}
          <Reveal delay={150}>
            <Bridge locks={locks} loading={loading} color={color} initials={initials} message={message} />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Bridge({
  locks,
  loading,
  color,
  initials,
  message,
}: {
  locks: Lock[];
  loading: boolean;
  color: string;
  initials: string;
  message: string;
}) {
  const previewColor = COLORS.find((c) => c.key === color) ?? COLORS[0];
  const previewLock = initials.trim().length >= 2
    ? { initials: initials.trim().toUpperCase(), color, message: message.trim() || null }
    : null;

  const allLocks = useMemo(() => {
    const list = [...locks];
    if (previewLock) list.unshift({ ...previewLock, id: "preview" } as Lock);
    return list;
  }, [locks, previewLock]);

  return (
    <div className="relative">
      {/* the bridge — a decorative chain/rail */}
      <div className="relative min-h-[28rem] overflow-hidden rounded-sm border border-gold/15 bg-gradient-to-b from-night/40 to-night-soft/60">
        {/* chain */}
        <svg
          className="pointer-events-none absolute inset-x-0 top-8 h-6 w-full text-gold/40"
          viewBox="0 0 800 24"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M0 12 Q 100 28 200 12 T 400 12 T 600 12 T 800 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>

        {/* locks hanging */}
        <div className="relative grid grid-cols-3 gap-x-4 gap-y-6 px-4 pt-16 pb-8 sm:grid-cols-4 sm:gap-x-6">
          {loading ? (
            <div className="col-span-full py-20 text-center font-cormorant text-base text-ivory-soft/50">
              Загружаем мост…
            </div>
          ) : allLocks.length === 0 ? (
            <div className="col-span-full py-20 text-center">
              <Heart className="mx-auto h-6 w-6 text-gold/40" />
              <p className="mt-3 font-cormorant text-base text-ivory-soft/60">
                Будьте первыми, кто повесит замок
              </p>
            </div>
          ) : (
            allLocks.map((lock, i) => (
              <Padlock
                key={lock.id ?? i}
                lock={lock}
                index={i}
                isPreview={lock.id === "preview"}
              />
            ))
          )}
        </div>

        {/* corner ornament */}
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-gold/30 to-transparent" />
      </div>

      {/* count */}
      <div className="mt-4 flex items-center justify-between font-cormorant text-sm text-ivory-soft/60">
        <span>
          {locks.length} {plural(locks.length, ["замок", "замка", "замков"])} на мосту
        </span>
        {previewLock ? (
          <span className="text-gold/70">предпросмотр вашего замка</span>
        ) : null}
      </div>
    </div>
  );
}

function Padlock({
  lock,
  index,
  isPreview,
}: {
  lock: Lock;
  index: number;
  isPreview?: boolean;
}) {
  const cfg = COLORS.find((c) => c.key === lock.color) ?? COLORS[0];
  // deterministic sway based on index
  const sway = (index % 3) - 1; // -1, 0, 1
  const delay = (index * 0.4) % 3;

  return (
    <div
      className={cn(
        "group relative flex flex-col items-center",
        isPreview && "opacity-60"
      )}
      style={{ transform: `rotate(${sway * 3}deg)` }}
    >
      {/* shackle */}
      <svg
        className="h-5 w-6 text-gold/50"
        viewBox="0 0 24 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="M6 18 V10 a6 6 0 0 1 12 0 V18" strokeLinecap="round" />
      </svg>
      {/* body */}
      <div
        className={cn(
          "relative -mt-1 flex h-16 w-12 flex-col items-center justify-center rounded-md border shadow-lg transition-transform duration-500 group-hover:scale-110",
          "animate-floaty"
        )}
        style={{
          backgroundColor: cfg.hex,
          borderColor: "rgba(0,0,0,0.2)",
          color: cfg.fg,
          animationDelay: `${delay}s`,
        }}
      >
        <span className="font-playfair text-xs font-bold tracking-wide">
          {lock.initials}
        </span>
        <span className="absolute -top-1 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-current opacity-30" />
        {/* keyhole */}
        <span className="mt-1 h-1.5 w-1 rounded-full bg-current opacity-40" />
      </div>
      {/* message tooltip on hover */}
      {lock.message ? (
        <div className="pointer-events-none absolute -bottom-2 left-1/2 z-10 w-32 -translate-x-1/2 translate-y-2 rounded-sm border border-gold/30 bg-night/95 px-2 py-1 text-center opacity-0 backdrop-blur-sm transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100">
          <p className="font-cormorant text-xs italic text-ivory-soft/80">
            «{lock.message}»
          </p>
        </div>
      ) : null}
      {isPreview ? (
        <span className="mt-2 font-cormorant text-[0.65rem] text-gold/70">ваш замок</span>
      ) : null}
    </div>
  );
}

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return forms[1];
  return forms[2];
}
