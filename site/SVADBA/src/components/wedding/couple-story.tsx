"use client";

import { wedding } from "@/lib/wedding-config";
import { Heart, Monogram, SectionHeading, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";

export function CoupleStory() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section id="story" className="relative overflow-hidden bg-night py-24 sm:py-32">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <Sprig className="pointer-events-none absolute -left-6 top-24 h-40 w-40 text-gold/15 rotate-12" />
      <Sprig className="pointer-events-none absolute -right-6 bottom-24 h-40 w-40 text-gold/15 -rotate-12 -scale-x-100" />

      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow={t("story.couple")}
            title={t("story.coupleTitle")}
            subtitle={content.concept}
          />
        </Reveal>

        <div className="mt-16 grid grid-cols-1 gap-8 md:grid-cols-2 md:gap-10">
          <Reveal>
            <PersonCard
              name={wedding.brideFull}
              role={t("story.bride")}
              image="/wedding/bride-portrait.png"
              quote={content.coupleQuotes.bride}
              initials={wedding.brideInitials}
            />
          </Reveal>
          <Reveal delay={150}>
            <PersonCard
              name={wedding.groomFull}
              role={t("story.groom")}
              image="/wedding/couple-silhouette.png"
              quote={content.coupleQuotes.groom}
              initials={wedding.groomInitials}
              mirrored
            />
          </Reveal>
        </div>

        {/* Timeline of the relationship */}
        <Reveal delay={120} className="mt-20">
          <div className="relative mx-auto max-w-3xl">
            <div className="ornament-line mb-10 text-gold">
              <Heart className="h-3 w-3" />
            </div>
            <ol className="relative space-y-10 before:absolute before:left-[7px] before:top-2 before:h-[calc(100%-1rem)] before:w-px before:bg-gradient-to-b before:from-gold/60 before:via-gold/30 before:to-transparent">
              {storyMilestones.map((m, i) => (
                <li key={i} className="relative pl-8">
                  <span className="absolute left-0 top-1.5 flex h-3.5 w-3.5 items-center justify-center rounded-full border border-gold bg-night">
                    <span className="h-1 w-1 rounded-full bg-gold" />
                  </span>
                  <p className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
                    {m.date}
                  </p>
                  <h3 className="mt-1 font-playfair text-2xl text-ivory">{m.title}</h3>
                  <p className="mt-1 font-cormorant text-base text-ivory-soft/75">
                    {m.desc}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </Reveal>

        <Reveal delay={150} className="mt-16 flex justify-center">
          <Monogram left={wedding.brideInitials} right={wedding.groomInitials} className="h-32 w-32 text-gold" />
        </Reveal>
      </div>
    </section>
  );
}

function PersonCard({
  name,
  role,
  image,
  quote,
  initials,
  mirrored = false,
}: {
  name: string;
  role: string;
  image: string;
  quote: string;
  initials: string;
  mirrored?: boolean;
}) {
  return (
    <article className="group relative card-luxe overflow-hidden rounded-sm">
      <div className={`grid grid-cols-[1fr_1.4fr] ${mirrored ? "rtl" : ""}`}>
        <div className="relative h-full min-h-[18rem] overflow-hidden">
          <img
            src={image}
            alt={name}
            className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-night/80 via-night/10 to-transparent" />
          <span className="absolute bottom-3 left-1/2 -translate-x-1/2 font-playfair text-5xl text-gold/70 drop-shadow-lg">
            {initials}
          </span>
        </div>
        <div className="flex flex-col justify-center gap-3 p-6 text-center sm:p-8">
          <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
            {role}
          </span>
          <h3 className="font-playfair text-3xl text-ivory">{name}</h3>
          <p className="font-script text-xl text-gold-soft">{quote}</p>
        </div>
      </div>
    </article>
  );
}

const storyMilestones = [
  {
    date: "Осень 2021",
    title: "Первая встреча",
    desc: "Книжный магазин у Большого театра. Она искала Бродского, он — стихи Цветаевой.",
  },
  {
    date: "Зима 2022",
    title: "Первый Новый год",
    desc: "Полночь на крыше с видом на Кремль и бокал горячего глинтвейна.",
  },
  {
    date: "Лето 2024",
    title: "Путешествие в Тоскану",
    desc: "Под виноградниками Кьянти прозвучало первое «навсегда».",
  },
  {
    date: "Весна 2026",
    title: "Предложение",
    desc: "1000 свечей и кольцо, спрятанное в букете белых пионов.",
  },
  {
    date: "22 октября 2026",
    title: "Свадьба",
    desc: "Тот самый день, который начнётся ровно в полночь.",
  },
];
