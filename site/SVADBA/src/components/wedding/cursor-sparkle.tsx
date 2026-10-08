"use client";

import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  life: number;
  size: number;
  drift: number;
};

/**
 * Subtle gold sparkle trail that follows the cursor on devices with a
 * precise pointer. Disabled on touch / coarse pointers to avoid jank.
 */
export function CursorSparkle() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particles = useRef<Particle[]>([]);
  const raf = useRef<number | null>(null);
  const last = useRef<{ x: number; y: number; t: number } | null>(null);

  useEffect(() => {
    const fine =
      typeof window !== "undefined" &&
      window.matchMedia?.("(pointer: fine)")?.matches;
    if (!fine) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      canvas.width = window.innerWidth * window.devicePixelRatio;
      canvas.height = window.innerHeight * window.devicePixelRatio;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    };
    resize();
    window.addEventListener("resize", resize);

    const onMove = (e: MouseEvent) => {
      const now = performance.now();
      const prev = last.current;
      // throttle particle spawning
      if (prev && now - prev.t < 24) return;
      last.current = { x: e.clientX, y: e.clientY, t: now };

      const count = Math.random() > 0.4 ? 2 : 1;
      for (let i = 0; i < count; i++) {
        particles.current.push({
          x: e.clientX + (Math.random() - 0.5) * 8,
          y: e.clientY + (Math.random() - 0.5) * 8,
          life: 1,
          size: 2 + Math.random() * 2.6,
          drift: (Math.random() - 0.5) * 0.6,
        });
      }
      if (particles.current.length > 140) {
        particles.current.splice(0, particles.current.length - 140);
      }
    };
    window.addEventListener("mousemove", onMove, { passive: true });

    const tick = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const arr = particles.current;
      for (let i = arr.length - 1; i >= 0; i--) {
        const p = arr[i];
        p.life -= 0.022;
        p.y -= 0.35;
        p.x += p.drift;
        if (p.life <= 0) {
          arr.splice(i, 1);
          continue;
        }
        const alpha = Math.max(0, p.life);
        const r = p.size * (0.6 + alpha * 0.8);
        // outer glow
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 4);
        grad.addColorStop(0, `rgba(240, 220, 160, ${alpha * 0.9})`);
        grad.addColorStop(0.4, `rgba(200, 169, 106, ${alpha * 0.35})`);
        grad.addColorStop(1, "rgba(200, 169, 106, 0)");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 4, 0, Math.PI * 2);
        ctx.fill();
        // bright core
        ctx.fillStyle = `rgba(255, 245, 220, ${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 0.5, 0, Math.PI * 2);
        ctx.fill();
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[60] hidden lg:block"
    />
  );
}
