"use client";

import { Heart, SectionHeading } from "./ornaments";
import { Reveal } from "./reveal";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";

export function Schedule() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section id="schedule" className="relative overflow-hidden bg-night py-24 sm:py-32">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-5xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow={t("schedule.eyebrow")}
            title={t("schedule.title")}
            subtitle={t("schedule.subtitle")}
          />
        </Reveal>

        <div className="mt-16 grid gap-8 md:grid-cols-[0.9fr_1.1fr] md:items-start">
          {/* Side image */}
          <Reveal className="md:sticky md:top-28">
            <div className="relative frame-gold overflow-hidden">
              <img
                src="/wedding/table-setting.png"
                alt={t("schedule.title")}
                className="aspect-[4/5] w-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-night/80 via-transparent to-transparent" />
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 text-center">
                <p className="font-script text-3xl text-ivory/95 drop-shadow-lg">
                  {t("schedule.untilMidnight")}
                </p>
                <p className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
                  {t("schedule.oneMoment")}
                </p>
              </div>
            </div>
          </Reveal>

          {/* Timeline */}
          <Reveal delay={120}>
            <ol className="relative space-y-6 before:absolute before:left-[88px] before:top-2 before:h-[calc(100%-1.5rem)] before:w-px before:bg-gradient-to-b before:from-gold/60 before:via-gold/25 before:to-transparent">
              {content.schedule.map((item, i) => (
                <li
                  key={i}
                  className="group relative flex items-start gap-6 rounded-sm border border-transparent p-3 transition-colors hover:border-gold/15 hover:bg-night-soft/60"
                >
                  <div className="w-[72px] shrink-0 pt-1 text-right">
                    <span className="font-playfair text-xl text-gold-gradient">
                      {item.time}
                    </span>
                  </div>
                  <span className="relative z-10 mt-2 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-gold bg-night">
                    <span className="h-1 w-1 rounded-full bg-gold group-hover:animate-pulse-gold" />
                  </span>
                  <div className="flex-1">
                    <h3 className="font-playfair text-xl text-ivory">{item.title}</h3>
                    <p className="mt-0.5 font-cormorant text-base text-ivory-soft/70">
                      {item.desc}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </Reveal>
        </div>

        <Reveal delay={150} className="mt-14 flex justify-center">
          <div className="ornament-line text-gold">
            <Heart className="h-3.5 w-3.5" />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
