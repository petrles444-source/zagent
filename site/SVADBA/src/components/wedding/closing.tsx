"use client";

import { wedding } from "@/lib/wedding-config";
import { Heart, Monogram, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";

function PrintIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9V3h12v6" />
      <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
      <rect x="6" y="14" width="12" height="8" rx="1" />
    </svg>
  );
}

export function Closing() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section className="relative overflow-hidden bg-night py-28 sm:py-36">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-25"
        style={{ backgroundImage: "url(/wedding/couple-silhouette.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-3xl px-6 text-center">
        <Reveal>
          <Monogram
            left={wedding.brideInitials}
            right={wedding.groomInitials}
            className="mx-auto h-28 w-28 text-gold"
          />
        </Reveal>
        <Reveal delay={120}>
          <p className="mt-8 font-script text-4xl text-gold-soft sm:text-5xl">
            {t("closing.withLove")}
          </p>
        </Reveal>
        <Reveal delay={200}>
          <h2 className="mt-4 font-playfair text-4xl text-ivory sm:text-5xl">
            {wedding.bride} <span className="text-gold/60">&</span> {wedding.groom}
          </h2>
        </Reveal>
        <Reveal delay={260}>
          <div className="mx-auto mt-7 flex items-center justify-center gap-3 text-gold">
            <span className="hairline w-16" />
            <Heart className="h-4 w-4 animate-flicker" />
            <span className="hairline w-16" />
          </div>
        </Reveal>
        <Reveal delay={320}>
          <p className="mt-7 font-cormorant text-xl italic leading-relaxed text-ivory-soft/85">
            {content.closingQuote}
          </p>
        </Reveal>
        <Reveal delay={380}>
          <p className="mt-8 font-playfair text-sm uppercase tracking-luxe text-gold">
            {wedding.dateLong} · {t("common.at")} {wedding.time}
          </p>
        </Reveal>
        <Reveal delay={420}>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <a href="#rsvp" className="btn-luxe">
              {t("closing.confirmVisit")}
            </a>
            <button onClick={() => window.print()} className="btn-ghost-luxe">
              <PrintIcon className="h-4 w-4" />
              {t("closing.keepAsKeepsake")}
            </button>
          </div>
        </Reveal>
        <Reveal delay={460}>
          <div className="mt-10 flex items-center justify-center gap-2 text-gold/50">
            <Sprig className="h-5 w-5" />
            <span className="font-cormorant text-sm text-ivory-soft/50">
              {wedding.hashtag}
            </span>
            <Sprig className="h-5 w-5 -scale-x-100" />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="relative mt-auto border-t border-gold/15 bg-night-soft">
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="flex flex-col items-center justify-between gap-6 text-center sm:flex-row sm:text-left">
          <div className="flex items-center gap-2.5">
            <Heart className="h-4 w-4 text-gold animate-flicker" />
            <span className="font-playfair text-sm tracking-wide-2 text-ivory uppercase">
              {wedding.bride} <span className="text-gold/60">&</span> {wedding.groom}
            </span>
          </div>
          <p className="font-cormorant text-sm text-ivory-soft/60">
            {wedding.dateLong} · {wedding.venueName}
          </p>
          <div className="flex items-center gap-4 font-cormorant text-sm text-ivory-soft/60">
            <a href={`mailto:${wedding.contactEmail}`} className="hover:text-gold transition-colors">
              {wedding.contactEmail}
            </a>
            <span className="text-gold/30">·</span>
            <a href={`tel:${wedding.contactPhone}`} className="hover:text-gold transition-colors">
              {wedding.contactPhone}
            </a>
          </div>
        </div>
        <div className="mt-6 border-t border-gold/10 pt-6 text-center">
          <p className="font-cormorant text-xs text-ivory-soft/40">
            Сделано с любовью и множеством свечей · © 2026 {wedding.bride} & {wedding.groom}
          </p>
        </div>
      </div>
    </footer>
  );
}
