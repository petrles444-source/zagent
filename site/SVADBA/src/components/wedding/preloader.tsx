"use client";

import { useEffect, useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { Heart, Monogram } from "./ornaments";
import { cn } from "@/lib/utils";

type Stage = "show" | "leaving" | "done";

/**
 * Elegant full-screen intro that plays once per session: gold monogram,
 * script names, a thin progress line, then fades away revealing the page.
 *
 * Lint-safe approach: we render nothing on the server (mount=false). On the
 * client's first effect we read sessionStorage/matchMedia and decide whether
 * to play or skip — those reads happen inside the rAF callback (not
 * synchronously in the effect body), which keeps the React-19
 * set-state-in-effect rule happy.
 */
export function Preloader() {
  const [stage, setStage] = useState<Stage>("show");
  const [progress, setProgress] = useState(0);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Defer to next frame so setState is not synchronous in the effect body
    // and to avoid SSR/CSR hydration mismatch.
    const raf = requestAnimationFrame(() => {
      setMounted(true);
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      const seen = window.sessionStorage.getItem("wedding-intro-seen") === "1";
      if (reduce || seen) {
        setStage("done");
        return;
      }
      window.sessionStorage.setItem("wedding-intro-seen", "1");

      let t1: ReturnType<typeof setTimeout> | undefined;
      let t2: ReturnType<typeof setTimeout> | undefined;
      let p = 0;
      const id = setInterval(() => {
        p += Math.random() * 14 + 6;
        if (p >= 100) {
          p = 100;
          clearInterval(id);
          setProgress(100);
          t1 = setTimeout(() => setStage("leaving"), 380);
          t2 = setTimeout(() => setStage("done"), 1280);
        } else {
          setProgress(p);
        }
      }, 110);

      cleanupFn = () => {
        clearInterval(id);
        if (t1) clearTimeout(t1);
        if (t2) clearTimeout(t2);
      };
    });

    let cleanupFn: () => void = () => {};
    return () => {
      cancelAnimationFrame(raf);
      cleanupFn();
    };
  }, []);

  if (!mounted || stage === "done") return null;

  return (
    <div
      className={cn(
        "fixed inset-0 z-[200] flex flex-col items-center justify-center bg-night transition-all duration-700",
        stage === "leaving" && "pointer-events-none opacity-0 backdrop-blur-0"
      )}
      aria-hidden={stage === "leaving"}
    >
      <div className="absolute inset-0 bg-radial-gold opacity-50" />
      <div className="absolute inset-0 bg-grain opacity-40" />

      <div
        className={cn(
          "relative flex flex-col items-center gap-6 transition-all duration-700",
          stage === "leaving" && "translate-y-4 scale-95 opacity-0"
        )}
      >
        <Monogram
          left={wedding.brideInitials}
          right={wedding.groomInitials}
          className="h-28 w-28 text-gold animate-fade-in"
        />

        <div className="flex items-center gap-3 text-gold">
          <span className="hairline w-12" />
          <Heart className="h-3.5 w-3.5 animate-flicker" />
          <span className="hairline w-12" />
        </div>

        <p className="font-script text-4xl text-gold-soft sm:text-5xl animate-fade-in">
          {wedding.bride}
          <span className="mx-2 text-gold/60">&</span>
          {wedding.groom}
        </p>

        <p className="font-playfair text-[0.66rem] uppercase tracking-luxe text-ivory-soft/60">
          {wedding.dateLong}
        </p>

        {/* progress */}
        <div className="mt-4 flex w-48 flex-col items-center gap-2">
          <div className="h-px w-full overflow-hidden bg-gold/15">
            <div
              className="h-full bg-gradient-to-r from-gold-soft via-gold to-gold-soft transition-[width] duration-150 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="font-cormorant text-xs text-gold/60 tabular-nums">
            {Math.round(progress)}%
          </span>
        </div>
      </div>

      {/* fade veil that lifts at the end */}
      <div
        className={cn(
          "pointer-events-none absolute inset-0 bg-night transition-opacity duration-700",
          stage === "leaving" ? "opacity-0" : "opacity-100"
        )}
      />
    </div>
  );
}
