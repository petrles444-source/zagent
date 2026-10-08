"use client";

import { useCallback, useEffect, useState } from "react";
import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { cn } from "@/lib/utils";

type Shot = {
  src: string;
  alt: string;
  caption: string;
  desc?: string;
  span?: "tall" | "wide" | "big";
};

const shots: Shot[] = [
  {
    src: "/wedding/bride-portrait.png",
    alt: "Портрет невесты",
    caption: "Невеста",
    desc: "Атлас, фата и тишина перед полуночью",
    span: "tall",
  },
  {
    src: "/wedding/flowers.png",
    alt: "Букет белых пионов",
    caption: "Пионы",
    desc: "Букет, собранный на рассвете",
    span: "wide",
  },
  {
    src: "/wedding/rings.png",
    alt: "Обручальные кольца",
    caption: "Кольца",
    desc: "Два круга, одна вечность",
  },
  {
    src: "/wedding/couple-silhouette.png",
    alt: "Силуэт пары на закате",
    caption: "Закат",
    desc: "Там, где небо встречает землю",
    span: "wide",
  },
  {
    src: "/wedding/hands-rings.png",
    alt: "Руки с кольцами",
    caption: "Клятвы",
    desc: "Руки, которые больше не отпустят",
  },
  {
    src: "/wedding/candle-bokeh.png",
    alt: "Свечи",
    caption: "Свечи",
    desc: "Триста огоньков для триста гостей",
  },
  {
    src: "/wedding/table-setting.png",
    alt: "Сервировка стола",
    caption: "Стол",
    desc: "Каждый прибор — маленькое обещание",
    span: "big",
  },
  {
    src: "/wedding/venue.png",
    alt: "Банкетный зал усадьбы",
    caption: "Усадьба",
    desc: "Зал, где ночь становится праздником",
    span: "wide",
  },
];

export function Gallery() {
  const [active, setActive] = useState<number | null>(null);

  const close = useCallback(() => setActive(null), []);
  const next = useCallback(
    () => setActive((i) => (i === null ? null : (i + 1) % shots.length)),
    []
  );
  const prev = useCallback(
    () => setActive((i) => (i === null ? null : (i - 1 + shots.length) % shots.length)),
    []
  );

  useEffect(() => {
    if (active === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [active, close, next, prev]);

  return (
    <section
      id="gallery"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-7xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Мгновения"
            title="Галерея"
            subtitle="Нажмите на любой кадр, чтобы увидеть его целиком. Листайте стрелками ← → или Esc для выхода."
          />
        </Reveal>

        <Reveal delay={120} className="mt-14">
          <div className="grid auto-rows-[220px] grid-cols-2 gap-4 sm:gap-5 md:grid-cols-4">
            {shots.map((s, i) => (
              <GalleryTile
                key={i}
                shot={s}
                index={i}
                onOpen={() => setActive(i)}
              />
            ))}
          </div>
        </Reveal>

        <Reveal delay={150} className="mt-12 flex items-center justify-center gap-3 text-gold">
          <span className="hairline w-16" />
          <Heart className="h-3.5 w-3.5" />
          <span className="font-cormorant text-base italic text-ivory-soft/70">
            {`#${"СофияАлександрПолночь"}`}
          </span>
          <Heart className="h-3.5 w-3.5" />
          <span className="hairline w-16" />
        </Reveal>
      </div>

      {active !== null && (
        <Lightbox
          shot={shots[active]}
          index={active}
          total={shots.length}
          onClose={close}
          onNext={next}
          onPrev={prev}
        />
      )}
    </section>
  );
}

function GalleryTile({
  shot,
  index,
  onOpen,
}: {
  shot: Shot;
  index: number;
  onOpen: () => void;
}) {
  const spanClass =
    shot.span === "tall"
      ? "row-span-2"
      : shot.span === "wide"
      ? "col-span-2"
      : shot.span === "big"
      ? "col-span-2 row-span-2"
      : "";

  return (
    <figure
      className={cn(
        "group relative cursor-pointer overflow-hidden rounded-sm border border-gold/15 bg-night",
        spanClass
      )}
      onClick={onOpen}
    >
      <img
        src={shot.src}
        alt={shot.alt}
        loading="lazy"
        className="h-full w-full object-cover transition-transform duration-[1.1s] ease-out group-hover:scale-110"
      />
      <div className="absolute inset-0 bg-gradient-to-t from-night/95 via-night/20 to-transparent opacity-80 transition-opacity duration-500 group-hover:opacity-95" />
      <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-500 group-hover:ring-gold/50" />
      {/* corner accents */}
      <span className="pointer-events-none absolute left-2 top-2 h-4 w-4 border-l border-t border-gold/0 transition-colors duration-500 group-hover:border-gold/70" />
      <span className="pointer-events-none absolute right-2 top-2 h-4 w-4 border-r border-t border-gold/0 transition-colors duration-500 group-hover:border-gold/70" />
      <span className="pointer-events-none absolute bottom-2 left-2 h-4 w-4 border-b border-l border-gold/0 transition-colors duration-500 group-hover:border-gold/70" />
      <span className="pointer-events-none absolute bottom-2 right-2 h-4 w-4 border-b border-r border-gold/0 transition-colors duration-500 group-hover:border-gold/70" />
      <figcaption className="absolute bottom-3 left-3 right-3 flex items-center justify-between">
        <span className="font-playfair text-sm tracking-wide-2 text-ivory uppercase drop-shadow-[0_1px_8px_rgba(0,0,0,0.9)]">
          {shot.caption}
        </span>
        <span className="font-cormorant text-xs text-gold-soft">
          {String(index + 1).padStart(2, "0")} / {String(shots.length).padStart(2, "0")}
        </span>
      </figcaption>
      <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 scale-50 rounded-full border border-gold/60 bg-night/50 px-4 py-1.5 font-playfair text-[0.66rem] uppercase tracking-luxe text-gold opacity-0 backdrop-blur-sm transition-all duration-500 group-hover:scale-100 group-hover:opacity-100">
        увеличить
      </span>
    </figure>
  );
}

function Lightbox({
  shot,
  index,
  total,
  onClose,
  onNext,
  onPrev,
}: {
  shot: Shot;
  index: number;
  total: number;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-night/95 backdrop-blur-md animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={shot.alt}
    >
      {/* ambient glow */}
      <div className="pointer-events-none absolute inset-0 bg-radial-gold opacity-50" />

      {/* Close */}
      <button
        onClick={onClose}
        className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-gold/40 text-gold transition-all hover:rotate-90 hover:bg-gold/10"
        aria-label="Закрыть"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>

      {/* Prev */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onPrev();
        }}
        className="absolute left-3 top-1/2 z-10 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-gold/30 text-gold transition-all hover:bg-gold/10 hover:border-gold/60 sm:left-6"
        aria-label="Предыдущее"
      >
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 6l-6 6 6 6" />
        </svg>
      </button>

      {/* Image */}
      <figure
        className="relative z-10 mx-auto flex max-h-[88vh] max-w-5xl flex-col items-center px-16"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="frame-gold relative overflow-hidden">
          <img
            key={shot.src}
            src={shot.src}
            alt={shot.alt}
            className="max-h-[78vh] max-w-full object-contain animate-fade-up"
          />
        </div>
        <figcaption className="mt-5 flex items-center gap-4 text-center">
          <span className="hairline w-10 sm:w-16" />
          <span>
            <span className="font-playfair text-lg uppercase tracking-wide-2 text-ivory">
              {shot.caption}
            </span>
            {shot.desc ? (
              <span className="mt-1 block font-cormorant text-base italic text-ivory-soft/70">
                {shot.desc}
              </span>
            ) : null}
          </span>
          <span className="hairline w-10 sm:w-16" />
        </figcaption>
        <span className="mt-3 font-cormorant text-sm text-gold/70 tabular-nums">
          {String(index + 1).padStart(2, "0")} / {String(total).padStart(2, "0")}
        </span>
      </figure>

      {/* Next */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onNext();
        }}
        className="absolute right-3 top-1/2 z-10 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-gold/30 text-gold transition-all hover:bg-gold/10 hover:border-gold/60 sm:right-6"
        aria-label="Следующее"
      >
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </button>

      {/* Thumbnails strip */}
      <div className="absolute bottom-4 left-1/2 z-10 hidden -translate-x-1/2 gap-2 rounded-full border border-gold/20 bg-night/60 px-3 py-2 backdrop-blur-md sm:flex">
        {Array.from({ length: total }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 rounded-full transition-all duration-300",
              i === index ? "w-6 bg-gold" : "w-1.5 bg-gold/30"
            )}
          />
        ))}
      </div>
    </div>
  );
}
