"use client";

import { wedding } from "@/lib/wedding-config";
import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { useI18n } from "@/lib/i18n-context";
import { useWeddingContent } from "@/hooks/use-wedding-content";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

export function Faq() {
  const { t } = useI18n();
  const content = useWeddingContent();

  return (
    <section className="relative overflow-hidden bg-night-soft py-24 sm:py-32">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-3xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow={t("faq.eyebrow")}
            title={t("faq.title")}
            subtitle={t("faq.subtitle")}
          />
        </Reveal>

        <Reveal delay={120} className="mt-12">
          <Accordion type="single" collapsible className="space-y-3">
            {content.faq.map((item, i) => (
              <AccordionItem
                key={i}
                value={`item-${i}`}
                className="card-luxe rounded-sm border-gold/15 px-5 sm:px-7"
              >
                <AccordionTrigger className="py-5 text-left hover:no-underline">
                  <span className="flex items-center gap-3">
                    <Heart className="h-3.5 w-3.5 shrink-0 text-gold" />
                    <span className="font-playfair text-lg text-ivory sm:text-xl">
                      {item.q}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-5">
                  <p className="pl-7 font-cormorant text-base leading-relaxed text-ivory-soft/80">
                    {item.a}
                  </p>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </Reveal>

        <Reveal delay={150} className="mt-12 text-center">
          <div className="ornament-line mx-auto w-64 text-gold">
            <Heart className="h-3 w-3" />
          </div>
          <p className="mt-5 font-cormorant text-lg text-ivory-soft/70">
            {t("faq.stillQuestions")}{" "}
            <a
              href={`mailto:${wedding.contactEmail}`}
              className="text-gold hover:text-gold-soft underline-offset-4 hover:underline"
            >
              {wedding.contactEmail}
            </a>
          </p>
        </Reveal>
      </div>
    </section>
  );
}
