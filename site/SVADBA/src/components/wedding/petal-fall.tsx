"use client";

import { useEffect, useRef } from "react";

type Petal = {
  x: number;
  y: number;
  size: number;
  speedY: number;
  speedX: number;
  angle: number;
  angleSpeed: number;
  hue: number;
  alpha: number;
};

/**
 * Subtle ambient layer of falling petals / gold dust that drifts down the
 * whole page. Rendered on a single fixed canvas (pointer-events-none) and
 * respects prefers-reduced-motion.
 *
 * Petals are tiny — a mix of warm ivory/gold "petal" ellipses and bright
 * gold "ember" dots — so the page feels alive without distracting.
 */
export function PetalFall() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduce) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0;
    let h = 0;
    let petals: Petal[] = [];

    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // density scales with viewport width, capped
      const count = Math.min(38, Math.max(14, Math.round(w / 48)));
      petals = Array.from({ length: count }, () => spawnPetal(w, h, true));
    };
    resize();
    window.addEventListener("resize", resize);

    let raf = 0;
    const tick = () => {
      ctx.clearRect(0, 0, w, h);
      for (const p of petals) {
        p.y += p.speedY;
        p.x += p.speedX + Math.sin(p.angle) * 0.4;
        p.angle += p.angleSpeed;

        if (p.y > h + 20) {
          Object.assign(p, spawnPetal(w, h, false));
        }
        if (p.x > w + 20) p.x = -10;
        if (p.x < -20) p.x = w + 10;

        drawPetal(ctx, p);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[1] opacity-70"
    />
  );
}

function spawnPetal(w: number, h: number, scatter: boolean): Petal {
  const isEmber = Math.random() > 0.62;
  return {
    x: Math.random() * w,
    y: scatter ? Math.random() * h : -10 - Math.random() * 40,
    size: isEmber ? 1 + Math.random() * 1.6 : 4 + Math.random() * 6,
    speedY: 0.25 + Math.random() * 0.7,
    speedX: (Math.random() - 0.5) * 0.5,
    angle: Math.random() * Math.PI * 2,
    angleSpeed: (Math.random() - 0.5) * 0.03,
    hue: isEmber ? 42 : Math.random() > 0.5 ? 38 : 30,
    alpha: isEmber ? 0.5 + Math.random() * 0.4 : 0.18 + Math.random() * 0.22,
  };
}

function drawPetal(ctx: CanvasRenderingContext2D, p: Petal) {
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(p.angle);
  ctx.globalAlpha = p.alpha;

  if (p.size <= 2.4) {
    // ember — small glowing dot
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, p.size * 3);
    g.addColorStop(0, "rgba(255, 240, 200, 0.9)");
    g.addColorStop(0.5, "rgba(200, 169, 106, 0.35)");
    g.addColorStop(1, "rgba(200, 169, 106, 0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, p.size * 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 248, 226, 0.95)";
    ctx.beginPath();
    ctx.arc(0, 0, p.size * 0.6, 0, Math.PI * 2);
    ctx.fill();
  } else {
    // petal — elongated ellipse with warm gradient
    const grad = ctx.createLinearGradient(0, -p.size, 0, p.size);
    grad.addColorStop(0, "rgba(244, 236, 224, 0.95)");
    grad.addColorStop(0.5, "rgba(200, 169, 106, 0.6)");
    grad.addColorStop(1, "rgba(120, 90, 50, 0.2)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(0, 0, p.size * 0.55, p.size, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}
