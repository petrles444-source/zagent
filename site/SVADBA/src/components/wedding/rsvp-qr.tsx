"use client";

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { Heart, Sprig } from "./ornaments";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type Variant = "rsvp" | "photos";

const CONFIG: Record<Variant, { hash: string; label: string; caption: string }> = {
  rsvp: {
    hash: "#rsvp",
    label: "Сканируйте для RSVP",
    caption: "Наведите камеру телефона на код — откроется форма подтверждения визита.",
  },
  photos: {
    hash: "#photos",
    label: "Делитесь фото вечера",
    caption: "Сканируйте, чтобы загрузить фото со свадьбы — лучшие появятся на стене после проверки.",
  },
};

/**
 * Renders a QR code that deep-links to a section of the page.
 * Guests scan it from a printed card / table display and land directly
 * on the RSVP form or photo upload.
 */
export function RsvpQRCode({ variant = "rsvp" }: { variant?: Variant }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const { toast } = useToast();
  const [url, setUrl] = useState("");
  const [ready, setReady] = useState(false);
  const cfg = CONFIG[variant];

  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      const target =
        typeof window !== "undefined"
          ? `${window.location.origin}${window.location.pathname}${cfg.hash}`
          : `https://sofia-alexander.ru${cfg.hash}`;
      setUrl(target);
      setReady(true);
    });
    return () => cancelAnimationFrame(raf);
  }, [cfg.hash]);

  useEffect(() => {
    if (!url || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const size = variant === "photos" ? 160 : 220;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    QRCode.toCanvas(
      canvas,
      url,
      {
        errorCorrectionLevel: "H",
        margin: 1,
        width: size * dpr,
        color: { dark: "#0b0908", light: "#f4ece0" },
      },
      (err) => {
        if (err) console.error("QR generation failed", err);
      }
    );
  }, [url, variant]);

  const downloadPng = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dataUrl = canvas.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = `sofia-alexander-${variant}-qr.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast({
      title: "QR-код сохранён",
      description: "Вставьте PNG в печатные материалы.",
    });
  };

  return (
    <div
      className={cn(
        "card-luxe relative flex flex-col items-center gap-4 rounded-sm p-6 text-center",
        variant === "photos" && "max-w-xs"
      )}
    >
      <span className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />

      <div className="flex items-center gap-2">
        <Heart className="h-3.5 w-3.5 text-gold animate-flicker" />
        <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
          {cfg.label}
        </span>
        <Heart className="h-3.5 w-3.5 text-gold animate-flicker" />
      </div>

      <div className="frame-gold relative p-3">
        <canvas ref={canvasRef} className="block rounded-sm" aria-label={cfg.label} />
        <Heart className="absolute -left-2 -top-2 h-3 w-3 text-gold/60" />
        <Heart className="absolute -right-2 -top-2 h-3 w-3 text-gold/60" />
        <Heart className="absolute -bottom-2 -left-2 h-3 w-3 text-gold/60" />
        <Heart className="absolute -bottom-2 -right-2 h-3 w-3 text-gold/60" />
      </div>

      <div className="ornament-line w-32 text-gold">
        <Sprig className="h-4 w-4" />
      </div>

      <p className={cn("font-cormorant text-sm italic leading-relaxed text-ivory-soft/70", variant === "photos" ? "max-w-[16rem]" : "max-w-xs")}>
        {cfg.caption}
      </p>

      <button
        onClick={downloadPng}
        disabled={!ready}
        className="btn-ghost-luxe disabled:opacity-60"
      >
        <DownloadIcon className="h-4 w-4" />
        Скачать PNG
      </button>

      <span className="pointer-events-none absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/30 to-transparent" />
    </div>
  );
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v12M7 11l5 5 5-5M5 20h14" />
    </svg>
  );
}
