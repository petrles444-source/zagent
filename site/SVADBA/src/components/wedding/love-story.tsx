"use client";

import { useEffect, useRef, useState } from "react";
import { Heart, SectionHeading, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";

type Chapter = {
  n: string;
  date: string;
  title: string;
  img: string;
  text: string;
  side: "left" | "right";
};

export function LoveStory() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section
      id="love-story"
      className="relative overflow-hidden bg-night py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-7xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow={t("story.eyebrow")}
            title={t("story.title")}
            subtitle={
              content.loveStory.length === 5
                ? t("story.subtitle")
                : ""
            }
          />
        </Reveal>

        {/* vertical rail with chapters */}
        <div className="relative mt-20">
          {/* central gold rail */}
          <div
            className="pointer-events-none absolute left-4 top-0 h-full w-px bg-gradient-to-b from-gold/50 via-gold/20 to-transparent md:left-1/2 md:-translate-x-1/2"
            aria-hidden="true"
          />

          <div className="flex flex-col gap-24 sm:gap-32">
            {content.loveStory.map((ch, i) => (
              <LoveChapter key={i} chapter={ch} index={i} />
            ))}
          </div>
        </div>

        <Reveal delay={150} className="mt-20 flex justify-center">
          <div className="ornament-line w-56 text-gold">
            <Sprig className="h-5 w-5" />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function LoveChapter({ chapter, index }: { chapter: Chapter; index: number }) {
  const isLeft = chapter.side === "left";
  const ref = useRef<HTMLDivElement | null>(null);
  const [progress, setProgress] = useState(0); // 0 → 1 as chapter enters viewport

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const update = () => {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      // 0 when chapter top hits viewport bottom, 1 when center crosses center
      const p = Math.max(
        0,
        Math.min(
          1,
          (vh - rect.top) / (vh + rect.height)
        )
      );
      setProgress(p);
      raf = 0;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const parallaxY = (0.5 - Math.min(1, Math.max(0, progress))) * 60;

  return (
    <div
      ref={ref}
      className={cn(
        "relative grid items-center gap-8 md:grid-cols-2 md:gap-16",
        !isLeft && "md:[&>div:first-child]:order-2"
      )}
    >
      {/* Chapter marker on the rail */}
      <div
        className="absolute left-4 top-0 z-10 -translate-x-1/2 md:left-1/2"
        aria-hidden="true"
      >
        <span
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-full border bg-night font-playfair text-xs transition-all duration-500",
            progress > 0.3 && progress < 0.8
              ? "border-gold text-gold scale-110 shadow-[0_0_18px_rgba(200,169,106,0.6)]"
              : "border-gold/40 text-gold/50"
          )}
        >
          {chapter.n}
        </span>
      </div>

      {/* Image side */}
      <div
        className={cn(
          "relative pl-12 md:pl-0",
          !isLeft && "md:order-2"
        )}
      >
        <div className="frame-gold relative overflow-hidden">
          <div className="relative aspect-[4/3] w-full overflow-hidden">
            <img
              src={chapter.img}
              alt={chapter.title}
              loading="lazy"
              className="h-full w-full object-cover transition-transform duration-[1.4s] ease-out"
              style={{
                transform: `translate3d(0, ${parallaxY}px, 0) scale(${1.05 + Math.min(0.08, progress * 0.08)})`,
                willChange: "transform",
              }}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-night/80 via-transparent to-transparent" />
            <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-700 group-hover:ring-gold/30" />
          </div>
          {/* chapter number overlay */}
          <span className="pointer-events-none absolute right-4 top-4 font-playfair text-5xl text-ivory/15 select-none">
            {chapter.n}
          </span>
        </div>
      </div>

      {/* Text side */}
      <div className={cn("pl-12 md:pl-0", isLeft ? "md:order-2" : "md:order-1")}>
        <div
          className={cn(
            "max-w-md",
            isLeft ? "md:ml-auto md:text-right" : "md:mr-auto md:text-left"
          )}
        >
          <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
            {chapter.date}
          </span>
          <h3 className="mt-3 font-playfair text-3xl text-ivory sm:text-4xl text-balance">
            {chapter.title}
          </h3>
          <div
            className={cn(
              "my-5 flex items-center gap-3 text-gold",
              isLeft ? "md:justify-end" : "md:justify-start"
            )}
          >
            <span className="hairline w-10" />
            <Heart className="h-3.5 w-3.5 animate-flicker" />
            <span className="hairline w-10" />
          </div>
          <p className="font-cormorant text-lg leading-relaxed text-ivory-soft/80">
            {chapter.text}
          </p>
        </div>
      </div>
    </div>
  );
}
