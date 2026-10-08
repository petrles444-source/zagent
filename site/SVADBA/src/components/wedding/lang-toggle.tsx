"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n-context";
import { LANGS } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * Compact RU/EN language toggle — sits in the nav bar on desktop and in
 * the mobile sheet. Persists choice in localStorage.
 */
export function LangToggle({ className }: { className?: string }) {
  const { lang, setLang } = useI18n();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      className={cn(
        "flex items-center rounded-full border border-gold/25 bg-night/40 p-0.5",
        className
      )}
      role="group"
      aria-label="Language switcher"
    >
      {LANGS.map((l) => (
        <button
          key={l.code}
          onClick={() => setLang(l.code)}
          aria-pressed={lang === l.code}
          className={cn(
            "rounded-full px-2.5 py-1 font-playfair text-[0.62rem] uppercase tracking-luxe transition-all duration-300",
            mounted && lang === l.code
              ? "bg-gold/20 text-gold"
              : "text-ivory-soft/50 hover:text-gold"
          )}
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}
