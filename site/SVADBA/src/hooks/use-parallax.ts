"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Lightweight scroll-parallax hook. Returns a ref to attach to an element and
 * an `offset` (in px) that smoothly changes as the element passes through the
 * viewport. Use it to translate background layers, portraits, etc.
 *
 * @param strength how strong the parallax is (default 0.12 = 12% of scroll)
 */
export function useParallax<T extends HTMLElement = HTMLDivElement>(strength = 0.12) {
  const ref = useRef<T | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;

    const update = () => {
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      // -1 when element top is at viewport bottom, +1 when bottom is above viewport top
      const progress = (vh / 2 - (rect.top + rect.height / 2)) / vh;
      setOffset(progress * 100 * strength);
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
  }, [strength]);

  return { ref, offset };
}
