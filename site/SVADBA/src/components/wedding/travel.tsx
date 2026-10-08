"use client";

import { wedding } from "@/lib/wedding-config";
import { Heart, SectionHeading, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { cn } from "@/lib/utils";

export function Travel() {
  return (
    <section
      id="travel"
      className="relative overflow-hidden bg-night py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-[0.10]"
        style={{ backgroundImage: "url(/wedding/hotel.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Логистика и ночлег"
            title="Где переночевать"
            subtitle="Чтобы ночь была по-настоящему вашей — выберите отель рядом с усадьбой или воспользуйтесь трансфером."
          />
        </Reveal>

        {/* Transfer band */}
        <Reveal delay={120} className="mt-14">
          <div className="grid gap-4 sm:grid-cols-2">
            {wedding.travel.transfer.map((t, i) => (
              <div
                key={i}
                className="card-luxe group relative flex items-center gap-5 rounded-sm p-5 transition-all hover:-translate-y-0.5"
              >
                <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-full border border-gold/40 bg-night/60 text-gold">
                  <span className="font-playfair text-base font-semibold leading-none">
                    {t.time.split(":")[0]}
                  </span>
                  <span className="font-cormorant text-[0.7rem] leading-none">
                    {t.time.split(":")[1]}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 font-playfair text-sm text-ivory">
                    <span className="uppercase tracking-wide-2">{t.from}</span>
                    <ArrowIcon className="h-3.5 w-3.5 text-gold" />
                    <span className="uppercase tracking-wide-2">{t.to}</span>
                  </div>
                  <p className="mt-1 font-cormorant text-sm text-ivory-soft/70">
                    {t.note}
                  </p>
                </div>
                <Sprig className="absolute right-3 top-3 h-5 w-5 text-gold/15" />
              </div>
            ))}
          </div>
        </Reveal>

        {/* Hotels grid */}
        <Reveal delay={180} className="mt-10">
          <div className="grid gap-5 md:grid-cols-3">
            {wedding.travel.hotels.map((h, i) => (
              <HotelCard key={i} hotel={h} />
            ))}
          </div>
        </Reveal>

        {/* Map */}
        <Reveal delay={200} className="mt-10">
          <div className="card-luxe relative overflow-hidden rounded-sm">
            <div className="aspect-[16/7] w-full">
              <iframe
                title="Карта — усадьба"
                src={wedding.travel.mapEmbed}
                className="h-full w-full grayscale-[0.35] contrast-110"
                style={{ border: 0, filter: "invert(0.92) hue-rotate(180deg) saturate(0.7)" }}
                loading="lazy"
                referrerPolicy="no-referrer-when-downgrade"
                allowFullScreen
              />
            </div>
            <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-gold/20" />
            <div className="pointer-events-none absolute left-0 top-0 h-px w-full bg-gradient-to-r from-transparent via-gold/60 to-transparent" />
          </div>
        </Reveal>

        <Reveal delay={150} className="mt-8 flex justify-center">
          <div className="ornament-line text-gold">
            <Heart className="h-3 w-3" />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function HotelCard({ hotel }: { hotel: (typeof wedding.travel.hotels)[number] }) {
  return (
    <article
      className={cn(
        "card-luxe group relative flex h-full flex-col overflow-hidden rounded-sm p-6 transition-all hover:-translate-y-1",
        hotel.featured && "border-gold/45 ring-1 ring-gold/20"
      )}
    >
      {hotel.featured ? (
        <span className="absolute right-4 top-4 flex items-center gap-1 rounded-full border border-gold/50 bg-gold/10 px-3 py-1 font-playfair text-[0.6rem] uppercase tracking-luxe text-gold">
          <Heart className="h-2.5 w-2.5" filled /> Рекомендуем
        </span>
      ) : null}

      <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
        {hotel.type}
      </span>
      <h3 className="mt-2 font-playfair text-2xl text-ivory">{hotel.name}</h3>
      <p className="mt-1 font-cormorant text-sm text-ivory-soft/60">{hotel.address}</p>

      <div className="my-4 h-px w-12 bg-gold/40" />

      <p className="font-playfair text-xl text-gold-gradient">{hotel.price}</p>

      <ul className="mt-4 space-y-2">
        {hotel.perks.map((p, i) => (
          <li key={i} className="flex items-center gap-2 font-cormorant text-sm text-ivory-soft/80">
            <Sprig className="h-4 w-4 shrink-0 text-gold/60" />
            {p}
          </li>
        ))}
      </ul>

      <span className="pointer-events-none absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/40 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
    </article>
  );
}

function ArrowIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
