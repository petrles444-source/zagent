"use client";

import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  rot: number;
  rotV: number;
  color: string;
  shape: "petal" | "ember" | "square";
  life: number;
  maxLife: number;
};

const COLORS = [
  "#c8a96a", // gold
  "#e6cd92", // light gold
  "#f4ece0", // ivory
  "#e7c9c0", // blush
  "#d8bd86", // gold soft
];

/**
 * One-shot confetti / petal burst. Pass `fire={true}` (or change the `seed`
 * number) to trigger a burst that originates near the top-center and rains
 * down across the viewport. Auto-cleans when all particles expire.
 *
 * Respects prefers-reduced-motion (renders nothing).
 */
export function ConfettiBurst({ fire, seed }: { fire: boolean; seed: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particles = useRef<Particle[]>([]);
  const raf = useRef<number | null>(null);
  const active = useRef(false);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduce || !fire) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // spawn a burst of petals + embers
    const count = 140;
    const originX = w * 0.5;
    const originY = h * 0.18;
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.4;
      const speed = 4 + Math.random() * 9;
      const shape: Particle["shape"] =
        Math.random() > 0.7 ? "ember" : Math.random() > 0.5 ? "square" : "petal";
      particles.current.push({
        x: originX + (Math.random() - 0.5) * 80,
        y: originY + (Math.random() - 0.5) * 40,
        vx: Math.cos(angle) * speed * (Math.random() * 0.6 + 0.4),
        vy: Math.sin(angle) * speed * 0.6 - 4 - Math.random() * 4,
        size: shape === "ember" ? 1.5 + Math.random() * 1.8 : 4 + Math.random() * 6,
        rot: Math.random() * Math.PI * 2,
        rotV: (Math.random() - 0.5) * 0.3,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
        shape,
        life: 0,
        maxLife: 220 + Math.random() * 120,
      });
    }
    active.current = true;

    const tick = () => {
      ctx.clearRect(0, 0, w, h);
      const arr = particles.current;
      for (let i = arr.length - 1; i >= 0; i--) {
        const p = arr[i];
        p.life += 1;
        p.vy += 0.12; // gravity
        p.vx *= 0.995;
        p.x += p.vx;
        p.y += p.vy;
        p.rot += p.rotV;

        if (p.life > p.maxLife || p.y > h + 30) {
          arr.splice(i, 1);
          continue;
        }
        draw(ctx, p);
      }
      if (arr.length === 0) {
        active.current = false;
        raf.current = null;
        ctx.clearRect(0, 0, w, h);
        return;
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);

    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      particles.current = [];
      ctx.clearRect(0, 0, w, h);
    };
  }, [fire, seed]);

  if (!fire) return null;
  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[80]"
    />
  );
}

function draw(ctx: CanvasRenderingContext2D, p: Particle) {
  const alpha = Math.max(0, 1 - p.life / p.maxLife);
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(p.rot);
  ctx.globalAlpha = alpha;

  if (p.shape === "ember") {
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, p.size * 4);
    g.addColorStop(0, "rgba(255, 240, 200, 0.95)");
    g.addColorStop(0.5, hexToRgba(p.color, 0.4));
    g.addColorStop(1, hexToRgba(p.color, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, p.size * 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 248, 226, 0.95)";
    ctx.beginPath();
    ctx.arc(0, 0, p.size * 0.7, 0, Math.PI * 2);
    ctx.fill();
  } else if (p.shape === "square") {
    ctx.fillStyle = p.color;
    ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.5);
  } else {
    // petal
    const grad = ctx.createLinearGradient(0, -p.size, 0, p.size);
    grad.addColorStop(0, "rgba(244, 236, 224, 0.95)");
    grad.addColorStop(0.6, p.color);
    grad.addColorStop(1, hexToRgba(p.color, 0.2));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(0, 0, p.size * 0.55, p.size, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function hexToRgba(hex: string, a: number) {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
