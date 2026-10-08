"use client";

import { useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { Heart, Monogram } from "./ornaments";
import { useToast } from "@/hooks/use-toast";

/** Target wedding date — kept in a module-level const so the canvas can read it. */
const TARGET = new Date(wedding.dateISO).getTime();

function getRemaining() {
  const total = Math.max(0, TARGET - Date.now());
  return {
    total,
    days: Math.floor(total / (1000 * 60 * 60 * 24)),
    hours: Math.floor((total / (1000 * 60 * 60)) % 24),
    minutes: Math.floor((total / (1000 * 60)) % 60),
    seconds: Math.floor((total / 1000) % 60),
  };
}

/**
 * Generates a downloadable share-card image (canvas → PNG) showing the
 * current countdown to the wedding. The card matches the site's
 * black-and-gold aesthetic and is sized for social sharing (1080×1080).
 */
export function ShareCardButton() {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    try {
      // load the bride portrait (for the card background) — use the
      // ambient bride portrait we already have.
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.src = "/wedding/bride-portrait.png";
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject(new Error("img"));
      }).catch(() => {
        /* continue without the portrait */
      });

      const SIZE = 1080;
      const canvas = document.createElement("canvas");
      canvas.width = SIZE;
      canvas.height = SIZE;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas");

      // background — night
      ctx.fillStyle = "#0b0908";
      ctx.fillRect(0, 0, SIZE, SIZE);

      // subtle radial gold glow at top
      const glow = ctx.createRadialGradient(SIZE / 2, 0, 0, SIZE / 2, 0, SIZE * 0.7);
      glow.addColorStop(0, "rgba(200, 169, 106, 0.22)");
      glow.addColorStop(1, "rgba(200, 169, 106, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, SIZE, SIZE);

      // bride portrait as faint backdrop
      if (img.complete && img.naturalWidth > 0) {
        ctx.save();
        ctx.globalAlpha = 0.18;
        // cover-fit the portrait on the right half
        const ratio = img.naturalWidth / img.naturalHeight;
        let dw = SIZE * 0.7;
        let dh = dw / ratio;
        if (dh < SIZE) {
          dh = SIZE;
          dw = dh * ratio;
        }
        ctx.drawImage(img, SIZE - dw, 0, dw, dh);
        // gradient fade left
        const fade = ctx.createLinearGradient(SIZE * 0.3, 0, SIZE, 0);
        fade.addColorStop(0, "#0b0908");
        fade.addColorStop(1, "rgba(11, 9, 8, 0)");
        ctx.globalAlpha = 1;
        ctx.fillStyle = fade;
        ctx.fillRect(SIZE * 0.3, 0, SIZE * 0.7, SIZE);
        ctx.restore();
      }

      // grain dots
      ctx.save();
      ctx.globalAlpha = 0.06;
      ctx.fillStyle = "#c8a96a";
      for (let i = 0; i < 120; i++) {
        ctx.beginPath();
        ctx.arc(
          Math.random() * SIZE,
          Math.random() * SIZE,
          Math.random() * 1.6,
          0,
          Math.PI * 2
        );
        ctx.fill();
      }
      ctx.restore();

      // double ring monogram (top centre)
      ctx.save();
      ctx.translate(SIZE / 2, 230);
      ctx.strokeStyle = "#c8a96a";
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(0, 0, 70, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.4;
      ctx.beginPath();
      ctx.arc(0, 0, 62, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#e8dcc8";
      ctx.font = "italic 38px serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(
        `${wedding.brideInitials} & ${wedding.groomInitials}`,
        0,
        2
      );
      ctx.restore();

      // script names
      ctx.fillStyle = "#d8bd86";
      ctx.font = "italic 72px 'Marck Script', cursive";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`${wedding.bride} & ${wedding.groom}`, SIZE / 2, 360);

      // hairline + heart
      ctx.strokeStyle = "rgba(200, 169, 106, 0.6)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(SIZE / 2 - 120, 420);
      ctx.lineTo(SIZE / 2 - 14, 420);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(SIZE / 2 + 14, 420);
      ctx.lineTo(SIZE / 2 + 120, 420);
      ctx.stroke();
      drawHeart(ctx, SIZE / 2, 420, 8, "#c8a96a");

      // big countdown number
      const t = getRemaining();
      const label =
        t.total <= 0
          ? "Сегодня!"
          : `${t.days} ${plural(t.days, ["день", "дня", "дней"])}`;
      ctx.fillStyle = "#f0dca8";
      const grad = ctx.createLinearGradient(0, 470, 0, 640);
      grad.addColorStop(0, "#f0dca8");
      grad.addColorStop(0.5, "#c8a96a");
      grad.addColorStop(1, "#9c7d45");
      ctx.fillStyle = grad;
      ctx.font = "700 150px 'Playfair Display', serif";
      ctx.fillText(label, SIZE / 2, 560);

      // "до свадьбы"
      ctx.fillStyle = "#b8a98f";
      ctx.font = "500 28px 'Playfair Display', serif";
      ctx.fillText("ДО НАШЕЙ СВАДЬБЫ", SIZE / 2, 640);

      // date
      ctx.fillStyle = "#e8dcc8";
      ctx.font = "500 36px 'Playfair Display', serif";
      ctx.fillText(wedding.dateLong.toUpperCase(), SIZE / 2, 720);
      ctx.fillStyle = "#b8a98f";
      ctx.font = "italic 26px serif";
      ctx.fillText(`в ${wedding.time} · ${wedding.venueCity}`, SIZE / 2, 770);

      // bottom hairline + hashtag
      ctx.strokeStyle = "rgba(200, 169, 106, 0.4)";
      ctx.beginPath();
      ctx.moveTo(SIZE / 2 - 160, 860);
      ctx.lineTo(SIZE / 2 + 160, 860);
      ctx.stroke();
      ctx.fillStyle = "#9c7d45";
      ctx.font = "italic 26px serif";
      ctx.fillText(wedding.hashtag, SIZE / 2, 900);

      // trigger download
      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = "sofia-alexander-countdown.png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      toast({
        title: "Карточка готова",
        description: "Скачайте PNG и поделитесь в соцсетях.",
      });
    } catch {
      toast({
        title: "Не удалось создать карточку",
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-center gap-3">
      <button onClick={generate} disabled={busy} className="btn-ghost-luxe disabled:opacity-60">
        <CardIcon className="h-4 w-4" />
        {busy ? "Создаём…" : "Карточка отсчёта"}
      </button>
      <StoryCardButton />
    </div>
  );
}

/** Generates an Instagram-story-sized (1080×1920) share card. */
function StoryCardButton() {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    try {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.src = "/wedding/couple-silhouette.png";
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject(new Error("img"));
      }).catch(() => {});

      const W = 1080;
      const H = 1920;
      const canvas = document.createElement("canvas");
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas");

      // bg
      ctx.fillStyle = "#0b0908";
      ctx.fillRect(0, 0, W, H);

      // portrait as full-bleed backdrop
      if (img.complete && img.naturalWidth > 0) {
        ctx.save();
        ctx.globalAlpha = 0.35;
        const ratio = img.naturalWidth / img.naturalHeight;
        let dw = W;
        let dh = dw / ratio;
        if (dh < H) {
          dh = H;
          dw = dh * ratio;
        }
        ctx.drawImage(img, (W - dw) / 2, (H - dh) / 2, dw, dh);
        ctx.restore();
      }

      // dark gradient overlays for text legibility
      const top = ctx.createLinearGradient(0, 0, 0, H * 0.45);
      top.addColorStop(0, "#0b0908");
      top.addColorStop(1, "rgba(11,9,8,0)");
      ctx.fillStyle = top;
      ctx.fillRect(0, 0, W, H * 0.45);

      const bottom = ctx.createLinearGradient(0, H * 0.55, 0, H);
      bottom.addColorStop(0, "rgba(11,9,8,0)");
      bottom.addColorStop(0.5, "#0b0908");
      bottom.addColorStop(1, "#0b0908");
      ctx.fillStyle = bottom;
      ctx.fillRect(0, H * 0.55, W, H * 0.45);

      // gold glow
      const glow = ctx.createRadialGradient(W / 2, H * 0.75, 0, W / 2, H * 0.75, W * 0.6);
      glow.addColorStop(0, "rgba(200, 169, 106, 0.18)");
      glow.addColorStop(1, "rgba(200, 169, 106, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, W, H);

      // monogram
      ctx.save();
      ctx.translate(W / 2, H * 0.15);
      ctx.strokeStyle = "#c8a96a";
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(0, 0, 90, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.4;
      ctx.beginPath();
      ctx.arc(0, 0, 80, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#e8dcc8";
      ctx.font = "italic 46px serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`${wedding.brideInitials} & ${wedding.groomInitials}`, 0, 3);
      ctx.restore();

      // script names
      ctx.fillStyle = "#d8bd86";
      ctx.font = "italic 90px 'Marck Script', cursive";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`${wedding.bride} & ${wedding.groom}`, W / 2, H * 0.28);

      // heart divider
      ctx.strokeStyle = "rgba(200, 169, 106, 0.5)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(W / 2 - 160, H * 0.34);
      ctx.lineTo(W / 2 - 20, H * 0.34);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(W / 2 + 20, H * 0.34);
      ctx.lineTo(W / 2 + 160, H * 0.34);
      ctx.stroke();
      drawHeart(ctx, W / 2, H * 0.34, 12, "#c8a96a");

      // big countdown
      const t = getRemaining();
      const label =
        t.total <= 0
          ? "Сегодня!"
          : `${t.days} ${plural(t.days, ["день", "дня", "дней"])}`;
      const grad2 = ctx.createLinearGradient(0, H * 0.55, 0, H * 0.7);
      grad2.addColorStop(0, "#f0dca8");
      grad2.addColorStop(0.5, "#c8a96a");
      grad2.addColorStop(1, "#9c7d45");
      ctx.fillStyle = grad2;
      ctx.font = "700 200px 'Playfair Display', serif";
      ctx.fillText(label, W / 2, H * 0.63);

      ctx.fillStyle = "#b8a98f";
      ctx.font = "500 36px 'Playfair Display', serif";
      ctx.fillText("ДО НАШЕЙ СВАДЬБЫ", W / 2, H * 0.72);

      // date
      ctx.fillStyle = "#e8dcc8";
      ctx.font = "500 44px 'Playfair Display', serif";
      ctx.fillText(wedding.dateLong.toUpperCase(), W / 2, H * 0.8);
      ctx.fillStyle = "#b8a98f";
      ctx.font = "italic 30px serif";
      ctx.fillText(`в ${wedding.time} · ${wedding.venueCity}`, W / 2, H * 0.84);

      // bottom bar
      ctx.strokeStyle = "rgba(200, 169, 106, 0.4)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(W * 0.2, H * 0.9);
      ctx.lineTo(W * 0.8, H * 0.9);
      ctx.stroke();
      ctx.fillStyle = "#9c7d45";
      ctx.font = "italic 32px serif";
      ctx.fillText(wedding.hashtag, W / 2, H * 0.93);

      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = "sofia-alexander-story.png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      toast({
        title: "Стори готова",
        description: "1080×1920 PNG — идеально для Instagram Story.",
      });
    } catch {
      toast({
        title: "Не удалось создать стори",
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <button onClick={generate} disabled={busy} className="btn-ghost-luxe disabled:opacity-60">
      <StoryIcon className="h-4 w-4" />
      {busy ? "Создаём…" : "Для стори"}
    </button>
  );
}

function StoryIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <rect x="6" y="2" width="12" height="20" rx="3" />
      <circle cx="12" cy="18" r="1" fill="currentColor" />
    </svg>
  );
}

function drawHeart(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  s: number,
  color: string
) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(s / 12, s / 12);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(0, 4);
  ctx.bezierCurveTo(-2, 0, -12, -2, -12, -8);
  ctx.bezierCurveTo(-12, -14, -6, -16, 0, -10);
  ctx.bezierCurveTo(6, -16, 12, -14, 12, -8);
  ctx.bezierCurveTo(12, -2, 2, 0, 0, 4);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return forms[1];
  return forms[2];
}

function CardIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="1.5" />
      <path d="M3 9h18M8 5v4M16 5v4" />
      <path d="M9 15h6" />
    </svg>
  );
}

void Monogram; // keep import for tree-shaking friendliness if needed elsewhere
