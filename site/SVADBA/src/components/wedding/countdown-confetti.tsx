"use client";

import { useEffect, useRef, useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { ConfettiBurst } from "./confetti-burst";

/**
 * Fires a celebratory petal/ember burst the moment the wedding countdown
 * reaches zero, and repeats it once at midnight on the wedding day each
 * time the page is loaded that day. Only triggers on the actual zero day.
 */
export function CountdownConfetti() {
  const target = new Date(wedding.dateISO).getTime();
  const [fire, setFire] = useState(false);
  const [seed, setSeed] = useState(0);
  const firedRef = useRef(false);

  useEffect(() => {
    const check = () => {
      const now = Date.now();
      // fire only if we are within 5 minutes after the target (the zero moment)
      if (now >= target && now <= target + 5 * 60 * 1000 && !firedRef.current) {
        firedRef.current = true;
        setSeed((s) => s + 1);
        setFire(true);
        // re-fire once after a few seconds for a layered effect
        setTimeout(() => setSeed((s) => s + 1), 2200);
      }
    };
    check();
    const id = setInterval(check, 1000);
    return () => clearInterval(id);
  }, [target]);

  // Dev / demo helper: also allow firing via the URL hash #celebrate
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onHash = () => {
      if (window.location.hash === "#celebrate" && !firedRef.current) {
        firedRef.current = true;
        setSeed((s) => s + 1);
        setFire(true);
        setTimeout(() => setSeed((s) => s + 1), 2200);
      }
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return <ConfettiBurst fire={fire} seed={seed} />;
}
