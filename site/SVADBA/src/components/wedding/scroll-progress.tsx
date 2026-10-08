"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Heart } from "./ornaments";

/**
 * Thin gold scroll-progress bar pinned to the top of the viewport, plus a
 * floating "back to top" button that fades in after the user scrolls past the
 * first viewport.
 */
export function ScrollProgress() {
  const [progress, setProgress] = useState(0);
  const [showTop, setShowTop] = useState(false);

  useEffect(() => {
    let raf = 0;
    const update = () => {
      const scrollTop = window.scrollY || 0;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const pct = docHeight > 0 ? Math.min(1, scrollTop / docHeight) : 0;
      setProgress(pct);
      setShowTop(scrollTop > window.innerHeight * 0.9);
      raf = 0;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <>
      {/* progress bar */}
      <div className="fixed inset-x-0 top-0 z-[55] h-[3px] bg-gold/10" aria-hidden="true">
        <div
          className="h-full bg-gradient-to-r from-gold-soft via-gold to-gold-soft shadow-[0_0_8px_rgba(200,169,106,0.7)] transition-[width] duration-150 ease-out"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      {/* back to top */}
      <button
        onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        aria-label="Наверх"
        className={cn(
          "fixed bottom-6 right-6 z-50 flex h-12 w-12 items-center justify-center rounded-full border border-gold/40 bg-night/70 text-gold backdrop-blur-md transition-all duration-500 hover:bg-gold/15 hover:border-gold",
          showTop
            ? "translate-y-0 opacity-100"
            : "pointer-events-none translate-y-4 opacity-0"
        )}
      >
        <span className="absolute inset-0 rounded-full animate-pulse-gold" />
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
        <Heart className="absolute -right-1 -top-1 h-3 w-3 text-gold animate-flicker" filled />
      </button>
    </>
  );
}
