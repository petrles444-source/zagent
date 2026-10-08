"use client";

import { wedding } from "@/lib/wedding-config";
import { SectionHeading, Heart, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { DressLookbook } from "./dress-lookbook";
import { useI18n } from "@/lib/i18n-context";
import { cn } from "@/lib/utils";

type Swatch = {
  name: string;
  hex: string;
  desc: string;
  tone: "deep" | "warm" | "light" | "accent";
};

const palette: Swatch[] = [
  { name: "Ночь", hex: "#0b0908", desc: "глубокий чёрный", tone: "deep" },
  { name: "Полночь", hex: "#14100d", desc: "тёмный графит", tone: "deep" },
  { name: "Антрацит", hex: "#211a15", desc: "костюм жениха", tone: "deep" },
  { name: "Золото", hex: "#c8a96a", desc: "аксессуары, акценты", tone: "accent" },
  { name: "Светлое золото", hex: "#e6cd92", desc: "украшения, драгоценности", tone: "accent" },
  { name: "Шампань", hex: "#e8dcc8", desc: "платья дам", tone: "warm" },
  { name: "Слоновая кость", hex: "#f4ece0", desc: "рубашки, фактура", tone: "light" },
  { name: "Пыльная роза", hex: "#e7c9c0", desc: "букет, лёгкие акценты", tone: "warm" },
];

export function DressPalette() {
  const { t } = useI18n();
  return (
    <section className="relative overflow-hidden bg-night-soft py-20 sm:py-24">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-5xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow={t("palette.eyebrow")}
            title={t("palette.title")}
            subtitle={wedding.dressCodeDetails}
          />
        </Reveal>

        <Reveal delay={120} className="mt-12">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {palette.map((s, i) => (
              <SwatchCard key={i} swatch={s} delay={i * 50} />
            ))}
          </div>
        </Reveal>

        <Reveal delay={150} className="mt-10">
          <div className="card-luxe flex flex-col items-center gap-4 rounded-sm p-6 text-center sm:flex-row sm:justify-center sm:gap-8">
            <div className="flex items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-full border border-gold/40">
                <Heart className="h-3.5 w-3.5 text-gold" filled />
              </span>
              <span className="font-playfair text-lg text-ivory">
                {wedding.dressCode}
              </span>
            </div>
            <span className="hidden h-6 w-px bg-gold/30 sm:block" />
            <p className="max-w-md font-cormorant text-base italic text-ivory-soft/70">
              Просим избегать чистого белого и кричащих оттенков. Палитра вечера — ночь, золото и пионы.
            </p>
          </div>
        </Reveal>

        <Reveal delay={200} className="mt-8 flex justify-center">
          <div className="ornament-line w-40 text-gold">
            <Sprig className="h-4 w-4" />
          </div>
        </Reveal>

        <DressLookbook />
      </div>
    </section>
  );
}

function SwatchCard({ swatch, delay }: { swatch: Swatch; delay: number }) {
  const isLight = swatch.tone === "light" || swatch.tone === "warm";
  return (
    <div
      className={cn(
        "card-luxe group relative overflow-hidden rounded-sm transition-all hover:-translate-y-1"
      )}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {/* colour block */}
      <div
        className="relative aspect-square w-full"
        style={{ backgroundColor: swatch.hex }}
      >
        <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-500 group-hover:ring-gold/40" />
        <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-black/20 opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
        {/* hex code on hover */}
        <span
          className={cn(
            "absolute bottom-2 right-2 font-mono text-[0.6rem] uppercase tracking-wide-2 transition-opacity duration-300",
            isLight ? "text-night/70" : "text-ivory/70",
            "opacity-0 group-hover:opacity-100"
          )}
        >
          {swatch.hex}
        </span>
        {/* tone dot */}
        <span
          className={cn(
            "absolute left-2 top-2 h-2 w-2 rounded-full ring-1 ring-white/20",
            swatch.tone === "accent" && "bg-gold",
            swatch.tone === "deep" && "bg-night",
            swatch.tone === "warm" && "bg-blush",
            swatch.tone === "light" && "bg-ivory"
          )}
        />
      </div>
      {/* label */}
      <div className="p-3 text-center">
        <p className="font-playfair text-sm text-ivory">{swatch.name}</p>
        <p className="mt-0.5 font-cormorant text-xs text-ivory-soft/60">{swatch.desc}</p>
      </div>
    </div>
  );
}
