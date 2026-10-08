"use client";

import { wedding } from "@/lib/wedding-config";
import { Heart, SectionHeading } from "./ornaments";
import { Reveal } from "./reveal";

export function WeddingParty() {
  return (
    <section
      id="party"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Наша свита"
            title="Свидетели и друзья"
            subtitle="Те, без кого эта ночь не состоялась бы. Они будут рядом от первой до последней свечи."
          />
        </Reveal>

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {wedding.party.map((person, i) => (
            <Reveal key={i} delay={i * 90}>
              <article className="card-luxe group relative overflow-hidden rounded-sm text-center transition-all hover:-translate-y-1">
                <div className="relative aspect-[3/4] w-full overflow-hidden">
                  <img
                    src={person.img}
                    alt={person.name}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-night via-night/20 to-transparent" />
                  <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-500 group-hover:ring-gold/40" />
                  {/* role badge */}
                  <span className="absolute left-1/2 top-4 -translate-x-1/2 rounded-full border border-gold/40 bg-night/60 px-3 py-1 font-playfair text-[0.62rem] uppercase tracking-luxe text-gold backdrop-blur-sm">
                    {person.role}
                  </span>
                </div>
                <div className="p-5">
                  <h3 className="font-playfair text-xl text-ivory">{person.name}</h3>
                  <p className="mt-1 font-cormorant text-sm italic text-gold-soft">
                    {person.relation}
                  </p>
                  <div className="mx-auto my-3 flex items-center justify-center gap-2 text-gold">
                    <span className="hairline w-8" />
                    <Heart className="h-2.5 w-2.5" />
                    <span className="hairline w-8" />
                  </div>
                  <p className="font-cormorant text-sm leading-relaxed text-ivory-soft/75">
                    {person.note}
                  </p>
                </div>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
