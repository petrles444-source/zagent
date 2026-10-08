"use client";

import { wedding } from "@/lib/wedding-config";
import { Heart, SectionHeading, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { CalendarShare } from "./calendar-share";
import { ShareCardButton } from "./share-card";
import { RsvpQRCode } from "./rsvp-qr";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";

export function EventDetails() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section
      id="details"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-[0.12]"
        style={{ backgroundImage: "url(/wedding/venue.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Детали торжества"
            title="Где и когда"
            subtitle="Всё, что нужно знать, чтобы провести с нами эту ночь."
          />
        </Reveal>

        <div className="mt-16 grid gap-6 md:grid-cols-3">
          <Reveal>
            <InfoCard
              icon={<CalendarIcon />}
              eyebrow="Дата"
              title={wedding.dateShort}
              lines={[wedding.dateLong, `в ${wedding.time}`, wedding.weekday]}
            />
          </Reveal>
          <Reveal delay={120}>
            <InfoCard
              icon={<PinIcon />}
              eyebrow="Место"
              title={wedding.venueName}
              lines={[wedding.venueCity, wedding.venueAddress]}
              action={{ href: wedding.venueMapUrl, label: "Открыть карту" }}
            />
          </Reveal>
          <Reveal delay={240}>
            <InfoCard
              icon={<DressIcon />}
              eyebrow="Дресс-код"
              title={wedding.dressCode}
              lines={[wedding.dressCodeDetails]}
            />
          </Reveal>
        </div>

        {/* Venue feature band */}
        <Reveal delay={150} className="mt-14">
          <div className="grid items-center gap-8 overflow-hidden rounded-sm border border-gold/20 card-luxe md:grid-cols-2">
            <div className="relative aspect-[4/3] overflow-hidden md:aspect-auto md:h-full">
              <img
                src="/wedding/venue.png"
                alt={wedding.venueName}
                className="h-full w-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-r from-transparent to-night/70" />
            </div>
            <div className="p-8 sm:p-10">
              <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
                {t("details.estate")}
              </span>
              <h3 className="mt-3 font-playfair text-3xl text-ivory sm:text-4xl">
                {wedding.venueName}
              </h3>
              <div className="my-5 ornament-line text-gold">
                <Heart className="h-3 w-3" />
              </div>
              <p className="font-cormorant text-lg leading-relaxed text-ivory-soft/80">
                {content.venueDescription}
              </p>
              <ul className="mt-6 space-y-2 font-cormorant text-base text-ivory-soft/75">
                {content.venuePerks.map((perk, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <Sprig className="h-4 w-4 shrink-0 text-gold/70" /> {perk}
                  </li>
                ))}
              </ul>
              <a
                href={wedding.venueMapUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-ghost-luxe mt-8"
              >
                Построить маршрут
              </a>
            </div>
          </div>
        </Reveal>

        <Reveal delay={200}>
          <CalendarShare />
          <div className="mt-4">
            <ShareCardButton />
          </div>
        </Reveal>

        {/* QR code for printed invitations */}
        <Reveal delay={250} className="mt-10 flex justify-center">
          <RsvpQRCode />
        </Reveal>
      </div>
    </section>
  );
}

function InfoCard({
  icon,
  eyebrow,
  title,
  lines,
  action,
}: {
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  lines: string[];
  action?: { href: string; label: string };
}) {
  return (
    <div className="group relative h-full card-luxe rounded-sm p-8 text-center transition-all duration-500 hover:-translate-y-1">
      <span className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />
      <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-gold/40 text-gold transition-colors group-hover:bg-gold/10">
        {icon}
      </div>
      <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
        {eyebrow}
      </span>
      <h3 className="mt-2 font-playfair text-2xl text-ivory">{title}</h3>
      <div className="mx-auto my-4 h-px w-12 bg-gold/40" />
      <div className="space-y-1 font-cormorant text-base text-ivory-soft/75">
        {lines.map((l, i) => (
          <p key={i}>{l}</p>
        ))}
      </div>
      {action ? (
        <a
          href={action.href}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-5 inline-block font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold hover:text-gold-soft"
        >
          {action.label} →
        </a>
      ) : null}
    </div>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.3}>
      <rect x="3" y="5" width="18" height="16" rx="1.5" />
      <path d="M3 9h18M8 3v4M16 3v4" strokeLinecap="round" />
      <circle cx="8" cy="14" r="0.8" fill="currentColor" />
      <circle cx="12" cy="14" r="0.8" fill="currentColor" />
      <circle cx="16" cy="14" r="0.8" fill="currentColor" />
    </svg>
  );
}
function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.3}>
      <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}
function DressIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.3} strokeLinejoin="round">
      <path d="M9 3l3 3 3-3M9 3l1.5 4.5L8 10l4 11 4-11-2.5-2.5L15 3" />
    </svg>
  );
}
