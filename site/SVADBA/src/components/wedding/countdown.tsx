"use client";

import { useEffect, useMemo, useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";

function getRemaining(target: number) {
  const total = Math.max(0, target - Date.now());
  const days = Math.floor(total / (1000 * 60 * 60 * 24));
  const hours = Math.floor((total / (1000 * 60 * 60)) % 24);
  const minutes = Math.floor((total / (1000 * 60)) % 60);
  const seconds = Math.floor((total / 1000) % 60);
  return { total, days, hours, minutes, seconds };
}

const units = [
  { key: "days", label: "Дней" },
  { key: "hours", label: "Часов" },
  { key: "minutes", label: "Минут" },
  { key: "seconds", label: "Секунд" },
] as const;

export function Countdown() {
  const target = useMemo(() => new Date(wedding.dateISO).getTime(), []);
  const [t, setT] = useState(() => getRemaining(target));
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Reveal real numbers after mount (avoids SSR/CSR hydration mismatch).
    const raf = requestAnimationFrame(() => setMounted(true));
    const id = setInterval(() => setT(getRemaining(target)), 1000);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(id);
    };
  }, [target]);

  const isPast = t.total <= 0;
  const poetic = getPoeticMessage(t.total);

  return (
    <section
      id="countdown"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-10"
        style={{ backgroundImage: "url(/wedding/candle-bokeh.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="До торжества осталось"
            title="Обратный отсчёт"
            subtitle="Каждая секунда приближает нас к полуночи, когда начнётся наш новый день."
          />
        </Reveal>

        <Reveal delay={150} className="mt-14">
          {isPast ? (
            <div className="mx-auto max-w-xl rounded-sm border border-gold/30 bg-night/60 p-10 text-center card-luxe">
              <p className="font-script text-4xl text-gold-soft">Сегодня наш день</p>
              <p className="mt-3 font-cormorant text-lg text-ivory-soft/80">
                Свадьба состоялась. Спасибо всем, кто разделил с нами эту ночь.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:gap-6 md:grid-cols-4">
              {units.map((u) => {
                const value = t[u.key];
                return (
                  <div
                    key={u.key}
                    className="group relative card-luxe overflow-hidden rounded-sm p-6 text-center sm:p-8"
                  >
                    <span className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />
                    <div className="font-playfair text-5xl font-semibold text-gold-gradient sm:text-6xl md:text-7xl tabular-nums">
                      {mounted ? String(value).padStart(2, "0") : "—"}
                    </div>
                    <div className="mt-3 font-playfair text-[0.7rem] uppercase tracking-luxe text-ivory-soft/70">
                      {u.label}
                    </div>
                    <span className="pointer-events-none absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/30 to-transparent" />
                  </div>
                );
              })}
            </div>
          )}
        </Reveal>

        <Reveal delay={250} className="mt-12 text-center">
          <div className="ornament-line mx-auto mb-4 w-40 text-gold">
            <Heart className="h-3 w-3 animate-flicker" />
          </div>
          <p className="font-script text-3xl text-gold-soft sm:text-4xl animate-fade-in">
            {poetic.line}
          </p>
          <p className="mt-3 font-cormorant text-lg italic text-ivory-soft/70">
            {poetic.sub}
          </p>
          <p className="mt-2 font-cormorant text-base text-ivory-soft/50">
            {wedding.dateLong} · в {wedding.time} · {wedding.venueCity}
          </p>
        </Reveal>

        {/* First-dance sub-timer — counts to 03:00 wedding night */}
        <Reveal delay={300} className="mt-10">
          <FirstDanceTimer />
        </Reveal>
      </div>
    </section>
  );
}

/** Sub-timer counting to the first dance at 03:00 on the wedding night. */
function FirstDanceTimer() {
  // wedding date + 3 hours = first dance (03:00 per schedule)
  const target = useMemo(
    () => new Date(wedding.dateISO).getTime() + 3 * 60 * 60 * 1000,
    []
  );
  const [remaining, setRemaining] = useState(() => Math.max(0, target - Date.now()));
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    const id = setInterval(
      () => setRemaining(Math.max(0, target - Date.now())),
      1000
    );
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(id);
    };
  }, [target]);

  const isPast = remaining <= 0;
  const hours = Math.floor(remaining / (1000 * 60 * 60));
  const minutes = Math.floor((remaining / (1000 * 60)) % 60);
  const seconds = Math.floor((remaining / 1000) % 60);

  return (
    <div className="mx-auto flex max-w-md items-center justify-center gap-3 rounded-full border border-gold/20 bg-night/40 px-5 py-3">
      <svg viewBox="0 0 24 24" className="h-5 w-5 text-gold/70" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
      <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold/70">
        Первый танец
      </span>
      {isPast ? (
        <span className="font-script text-lg text-gold-soft">уже звучит</span>
      ) : (
        <span className="font-playfair text-base text-ivory tabular-nums">
          {mounted
            ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
            : "—:—:—"}
        </span>
      )}
    </div>
  );
}

/** Time-aware poetic message that shifts as the wedding approaches. */
function getPoeticMessage(totalMs: number) {
  const days = totalMs / (1000 * 60 * 60 * 24);
  const hours = totalMs / (1000 * 60 * 60);
  if (totalMs <= 0) {
    return {
      line: "Сегодня наш день",
      sub: "Спасибо всем, кто разделил с нами эту ночь.",
    };
  }
  if (days >= 30) {
    return {
      line: "Ещё столько вечеров до нашей ночи",
      sub: "Каждый закат приближает нас к полуночи.",
    };
  }
  if (days >= 14) {
    return {
      line: "Две недели до навсегда",
      sub: "Мы уже считаем свечи и подбираем музыку.",
    };
  }
  if (days >= 7) {
    return {
      line: "Эта неделя — последняя",
      sub: "До того, как начнётся наш новый день.",
    };
  }
  if (days >= 2) {
    return {
      line: "Совсем чуть-чуть",
      sub: "Пионы уже заказаны, свечи расставлены.",
    };
  }
  if (days >= 1) {
    return {
      line: "Завтра — наш день",
      sub: "Фата готова, кольца ждут.",
    };
  }
  if (hours >= 6) {
    return {
      line: "Сегодня. Уже сегодня.",
      sub: "Мы начинаем собирать букет.",
    };
  }
  if (hours >= 1) {
    return {
      line: "Часы до полуночи",
      sub: "Свечи зажгутся совсем скоро.",
    };
  }
  return {
    line: "Минуты до нашей ночи",
    sub: "Мы уже надеваем наряды.",
  };
}
