"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Heart } from "./ornaments";
import { LangToggle } from "./lang-toggle";
import { useI18n } from "@/lib/i18n-context";
import type { TranslationKey } from "@/lib/i18n";

const links: { href: string; key: TranslationKey }[] = [
  { href: "#hero", key: "nav.home" },
  { href: "#countdown", key: "nav.countdown" },
  { href: "#love-story", key: "nav.loveStory" },
  { href: "#story", key: "nav.about" },
  { href: "#party", key: "nav.party" },
  { href: "#details", key: "nav.details" },
  { href: "#travel", key: "nav.travel" },
  { href: "#schedule", key: "nav.schedule" },
  { href: "#tables", key: "nav.tables" },
  { href: "#gallery", key: "nav.gallery" },
  { href: "#photos", key: "nav.photos" },
  { href: "#rsvp", key: "nav.rsvp" },
  { href: "#guestbook", key: "nav.guestbook" },
  { href: "#love-locks", key: "nav.locks" },
];

export function SiteNav() {
  const { t } = useI18n();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-all duration-500",
        scrolled
          ? "bg-night/85 backdrop-blur-md border-b border-gold/15 py-3"
          : "bg-transparent py-5"
      )}
    >
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-5 sm:px-8">
        <a href="#hero" className="group flex items-center gap-2.5">
          <Heart className="h-4 w-4 text-gold animate-flicker" />
          <span className="font-playfair text-sm tracking-wide-2 text-ivory uppercase">
            София <span className="text-gold/70">&</span> Александр
          </span>
        </a>

        <ul className="hidden items-center gap-6 xl:flex">
          {links.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-ivory-soft/75 hover:text-gold transition-colors duration-300 relative group"
              >
                {t(l.key)}
                <span className="absolute -bottom-1 left-0 h-px w-0 bg-gold transition-all duration-300 group-hover:w-full" />
              </a>
            </li>
          ))}
          <li>
            <LangToggle />
          </li>
        </ul>

        <div className="flex items-center gap-2 xl:hidden">
          <LangToggle />
          <button
            aria-label="Меню"
            onClick={() => setOpen((v) => !v)}
            className="flex flex-col gap-1.5 p-2"
          >
            <span
              className={cn(
                "block h-px w-6 bg-gold transition-all duration-300",
                open && "translate-y-[7px] rotate-45"
              )}
            />
            <span
              className={cn(
                "block h-px w-6 bg-gold transition-all duration-300",
                open && "opacity-0"
              )}
            />
            <span
              className={cn(
                "block h-px w-6 bg-gold transition-all duration-300",
                open && "-translate-y-[7px] -rotate-45"
              )}
            />
          </button>
        </div>
      </nav>

      {/* Mobile sheet */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-500 bg-night/95 backdrop-blur-md xl:hidden",
          open ? "max-h-[32rem] border-t border-gold/15" : "max-h-0"
        )}
      >
        <ul className="flex flex-col px-6 py-4">
          {links.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                onClick={() => setOpen(false)}
                className="block py-3 font-playfair text-sm uppercase tracking-wide-2 text-ivory-soft/80 hover:text-gold border-b border-gold/10"
              >
                {t(l.key)}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </header>
  );
}
