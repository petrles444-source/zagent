"use client";

import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { useI18n } from "@/lib/i18n-context";

type Look = {
  img: string;
  titleKey: "dress" | "tuxedo" | "rose";
  hex: string;
};

const looks: Look[] = [
  { img: "/wedding/look-dress.png", titleKey: "dress", hex: "#e8dcc8" },
  { img: "/wedding/look-tuxedo.png", titleKey: "tuxedo", hex: "#14100d" },
  { img: "/wedding/look-rose.png", titleKey: "rose", hex: "#e7c9c0" },
];

const LOOK_LABELS: Record<Look["titleKey"], { ru: string; en: string; descRu: string; descEn: string }> = {
  dress: {
    ru: "Шампань · слоновая кость",
    en: "Champagne · ivory",
    descRu: "Длинное атласное платье — классика вечера.",
    descEn: "A long satin gown — an evening classic.",
  },
  tuxedo: {
    ru: "Чёрный смокинг",
    en: "Black tuxedo",
    descRu: "Смокинг с галстуком-бабочкой для джентльменов.",
    descEn: "A tuxedo with a bow tie for gentlemen.",
  },
  rose: {
    ru: "Пыльная роза",
    en: "Dusty rose",
    descRu: "Лёгкое шифоновое платье для романтичных образов.",
    descEn: "A soft chiffon gown for romantic looks.",
  },
};

export function DressLookbook() {
  const { t, lang } = useI18n();

  return (
    <Reveal delay={200} className="mt-12">
      <div className="flex items-center justify-center gap-3 text-gold">
        <span className="hairline w-12" />
        <Heart className="h-3 w-3" />
        <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
          {t("lookbook.eyebrow")}
        </span>
        <Heart className="h-3 w-3" />
        <span className="hairline w-12" />
      </div>

      <div className="mt-8 grid gap-5 sm:grid-cols-3">
        {looks.map((l, i) => (
          <article
            key={i}
            className="group relative overflow-hidden rounded-sm border border-gold/15 bg-night"
          >
            <div className="relative aspect-[3/4] w-full overflow-hidden">
              <img
                src={l.img}
                alt={LOOK_LABELS[l.titleKey][lang]}
                loading="lazy"
                className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-night via-night/20 to-transparent" />
              <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-500 group-hover:ring-gold/40" />
              {/* colour chip */}
              <span
                className="absolute right-3 top-3 h-6 w-6 rounded-full border border-gold/30 shadow-inner"
                style={{ backgroundColor: l.hex }}
                aria-hidden="true"
              />
              {/* caption */}
              <div className="absolute bottom-4 left-4 right-4 text-center">
                <h4 className="font-playfair text-base text-ivory">
                  {LOOK_LABELS[l.titleKey][lang]}
                </h4>
                <p className="mt-1 font-cormorant text-sm italic text-ivory-soft/70">
                  {lang === "ru" ? LOOK_LABELS[l.titleKey].descRu : LOOK_LABELS[l.titleKey].descEn}
                </p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </Reveal>
  );
}
