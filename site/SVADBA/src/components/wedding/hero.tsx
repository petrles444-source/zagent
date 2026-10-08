"use client";

import { useEffect, useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { Heart } from "./ornaments";
import { useParallax } from "@/hooks/use-parallax";

export function Hero() {
  const { ref: bgRef, offset: bgOffset } = useParallax<HTMLDivElement>(0.18);
  const { ref: portraitRef, offset: portraitOffset } = useParallax<HTMLDivElement>(0.1);

  return (
    <section
      id="hero"
      className="relative min-h-[100svh] w-full overflow-hidden bg-night"
    >
      {/* Background textures */}
      <div className="absolute inset-0 bg-grain opacity-60" aria-hidden="true" />
      <div className="absolute inset-0 bg-radial-gold" aria-hidden="true" />
      {/* Candle bokeh layer */}
      <div
        ref={bgRef}
        className="absolute inset-[-10%] bg-cover bg-center opacity-30"
        style={{
          backgroundImage: "url(/wedding/candle-bokeh.png)",
          transform: `translate3d(0, ${bgOffset}px, 0)`,
          willChange: "transform",
        }}
        aria-hidden="true"
      />
      {/* On mobile/tablet the bride portrait becomes an ambient backdrop */}
      <div
        className="absolute inset-0 bg-cover bg-center opacity-40 lg:hidden"
        style={{ backgroundImage: "url(/wedding/bride-portrait.png)", backgroundPosition: "75% 25%" }}
        aria-hidden="true"
      />
      <div
        className="absolute inset-0 bg-gradient-to-b from-night via-night/75 to-night lg:hidden"
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative z-10 mx-auto grid min-h-[100svh] max-w-7xl grid-cols-1 items-center gap-8 px-6 pb-24 pt-24 sm:gap-10 sm:px-10 sm:pt-28 lg:grid-cols-[1.05fr_0.95fr] lg:gap-6 lg:pt-24">
        {/* Left — invitation typography */}
        <div className="flex flex-col items-center text-center lg:items-start lg:text-left animate-fade-up">
          <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold animate-fade-in">
            Save the Date
          </span>

          <p className="mt-4 font-script text-4xl text-gold-soft leading-none sm:mt-6 sm:text-6xl md:text-7xl animate-fade-in">
            {wedding.bride}
            <span className="mx-2 text-gold/60">&</span>
            {wedding.groom}
          </p>

          <div className="my-5 flex items-center gap-3 text-gold sm:my-7">
            <span className="hairline w-12 sm:w-16" />
            <Heart className="h-4 w-4 animate-flicker" />
            <span className="hairline w-12 sm:w-16" />
          </div>

          <h1 className="font-playfair text-5xl font-semibold leading-[0.95] text-ivory sm:text-7xl md:text-8xl lg:text-[7.5rem]">
            <span className="block">День</span>
            <span className="mt-1 block text-gold-gradient animate-shimmer bg-clip-text">
              СВАДЬБА
            </span>
          </h1>

          <div className="my-5 flex items-center gap-3 text-gold sm:my-7">
            <span className="hairline w-10 sm:w-14" />
            <Heart className="h-3.5 w-3.5" />
            <span className="hairline w-10 sm:w-14" />
          </div>

          <p className="font-playfair text-xl uppercase tracking-wide-2 text-ivory sm:text-2xl">
            {wedding.dateLong}
          </p>
          <p className="mt-2 font-cormorant text-lg italic text-ivory-soft/80">
            в {wedding.time} · {wedding.weekday}
          </p>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-4 lg:justify-start">
            <a href="#rsvp" className="btn-luxe">
              Подтвердить визит
            </a>
            <a href="#countdown" className="btn-ghost-luxe">
              Обратный отсчёт
            </a>
          </div>
        </div>

        {/* Right — bride portrait in ornate frame (desktop only; mobile uses ambient backdrop) */}
        <div
          ref={portraitRef}
          className="relative mx-auto hidden w-full lg:block"
          style={{ transform: `translate3d(0, ${portraitOffset}px, 0)`, willChange: "transform" }}
        >
          <div className="relative frame-gold animate-fade-in">
            <div className="relative aspect-[3/4] w-full overflow-hidden">
              <img
                src="/wedding/bride-portrait.png"
                alt="Портрет невесты в день свадьбы"
                className="h-full w-full object-cover object-top"
                loading="eager"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-night/70 via-transparent to-transparent" />
              <div className="absolute inset-0 bg-gradient-to-r from-night/40 via-transparent to-night/20" />
            </div>
            {/* corner flourishes */}
            <span className="pointer-events-none absolute -left-2 -top-2 text-gold/80">
              <Corner />
            </span>
            <span className="pointer-events-none absolute -right-2 -top-2 rotate-90 text-gold/80">
              <Corner />
            </span>
            <span className="pointer-events-none absolute -bottom-2 -right-2 rotate-180 text-gold/80">
              <Corner />
            </span>
            <span className="pointer-events-none absolute -bottom-2 -left-2 -rotate-90 text-gold/80">
              <Corner />
            </span>

            {/* caption ribbon */}
            <div className="pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 text-center">
              <p className="font-script text-2xl text-ivory/90 drop-shadow-lg">
                с любовью
              </p>
            </div>
          </div>

          {/* Spinning vinyl badge — appears + spins when ambient audio is on */}
          <HeroVinylBadge />


          {/* floating peonies accent */}
          <div className="absolute -right-3 -top-3 hidden h-20 w-20 rounded-full bg-gold/10 blur-xl sm:block" aria-hidden="true" />
          <div className="absolute -bottom-4 -left-4 hidden h-24 w-24 rounded-full bg-blush/10 blur-2xl sm:block" aria-hidden="true" />
        </div>
      </div>

      {/* Scroll hint */}
      <a
        href="#countdown"
        className="absolute bottom-5 left-1/2 z-20 hidden -translate-x-1/2 flex-col items-center gap-2 text-gold sm:flex"
        aria-label="Прокрутить вниз"
      >
        <span className="font-playfair text-[0.62rem] uppercase tracking-luxe">
          Листайте
        </span>
        <span className="relative flex h-9 w-5 items-start justify-center rounded-full border border-gold/50 p-1">
          <span className="block h-2 w-1 rounded-full bg-gold animate-scroll-hint" />
        </span>
      </a>
    </section>
  );
}

function Corner() {
  return (
    <svg viewBox="0 0 80 80" className="h-10 w-10" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round">
      <path d="M4 28 V4 H28" />
      <path d="M4 28 C 16 26 26 16 28 4" />
      <circle cx="4" cy="4" r="1.6" fill="currentColor" />
      <path d="M10 10 H22 M10 10 V22" opacity="0.6" />
    </svg>
  );
}

/**
 * A small spinning vinyl badge that overlays the hero portrait. It only
 * appears (and spins) when the ambient audio is toggled on — polling
 * localStorage for the `wedding-ambient-audio` value (set by the
 * AmbientAudio component). Also listens for the `storage` event so it
 * reacts instantly to cross-tab toggle.
 */
function HeroVinylBadge() {
  const [audioOn, setAudioOn] = useState(false);

  useEffect(() => {
    const check = () => {
      try {
        setAudioOn(localStorage.getItem("wedding-ambient-audio") === "on");
      } catch {
        /* ignore */
      }
    };
    check();
    const id = setInterval(check, 1500);
    const onStorage = (e: StorageEvent) => {
      if (e.key === "wedding-ambient-audio") check();
    };
    window.addEventListener("storage", onStorage);
    return () => {
      clearInterval(id);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  if (!audioOn) return null;

  return (
    <div
      className="pointer-events-none absolute -left-5 bottom-8 z-20 hidden sm:block"
      style={{ animation: "vinyl-spin 3s linear infinite" }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 40 40" className="h-12 w-12 drop-shadow-[0_4px_12px_rgba(0,0,0,0.6)]">
        <defs>
          <radialGradient id="hero-vinyl" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#0b0908" />
            <stop offset="45%" stopColor="#1a1410" />
            <stop offset="80%" stopColor="#0b0908" />
            <stop offset="100%" stopColor="#211a15" />
          </radialGradient>
        </defs>
        <circle cx="20" cy="20" r="18" fill="url(#hero-vinyl)" stroke="#c8a96a" strokeWidth="0.5" />
        <circle cx="20" cy="20" r="14" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.3" />
        <circle cx="20" cy="20" r="11" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.25" />
        <circle cx="20" cy="20" r="8" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.2" />
        <circle cx="20" cy="20" r="5.5" fill="#c8a96a" />
        <circle cx="20" cy="20" r="1" fill="#0b0908" />
      </svg>
    </div>
  );
}
