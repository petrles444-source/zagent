"use client";

import { useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { Heart } from "./ornaments";
import { useToast } from "@/hooks/use-toast";

/**
 * "Add to calendar" (.ics) + native share / copy-link buttons.
 * Generates a valid iCalendar file entirely on the client and triggers a
 * download — works on iOS Calendar, Google Calendar, Outlook, Apple Calendar.
 */
export function CalendarShare() {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const onAddToCalendar = () => {
    const ics = buildIcs();
    const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "sofia-alexander-wedding.ics";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast({
      title: "Добавлено в календарь",
      description: "Файл .ics скачан — откройте его, чтобы импортировать событие.",
    });
  };

  const onShare = async () => {
    const shareData = {
      title: "София & Александр — 22 октября 2026",
      text: "День свадьбы. 22 октября 2026, в полночь. Будем рады видеть вас!",
      url: typeof window !== "undefined" ? window.location.href : "",
    };
    try {
      if (navigator.share) {
        await navigator.share(shareData);
        return;
      }
    } catch {
      /* user cancelled — fall through to copy */
    }
    try {
      await navigator.clipboard.writeText(shareData.url);
      setCopied(true);
      toast({ title: "Ссылка скопирована", description: "Поделитесь ею с близкими." });
      setTimeout(() => setCopied(false), 2500);
    } catch {
      toast({
        title: "Не удалось скопировать",
        description: "Скопируйте ссылку из адресной строки вручную.",
        variant: "destructive",
      });
    }
  };

  return (
    <div className="mt-8 flex flex-col items-center gap-4">
      <div className="ornament-line w-56 text-gold">
        <Heart className="h-3 w-3" />
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button onClick={onAddToCalendar} className="btn-luxe">
          <CalendarIcon className="h-4 w-4" />
          В календарь
        </button>
        <button onClick={onShare} className="btn-ghost-luxe">
          <ShareIcon className="h-4 w-4" />
          {copied ? "Скопировано!" : "Поделиться"}
        </button>
      </div>
    </div>
  );
}

/** Build a minimal but valid iCalendar VEVENT for the wedding. */
function buildIcs(): string {
  const start = new Date(wedding.dateISO);
  // event lasts until 07:00 next morning
  const end = new Date(start.getTime() + 7 * 60 * 60 * 1000);

  const dtStamp = new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const dtStart = toIcsLocal(start);
  const dtEnd = toIcsLocal(end);

  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Sofia & Alexander//Wedding//RU",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${wedding.dateISO}@sofia-alexander.ru`,
    `DTSTAMP:${dtStamp}`,
    `DTSTART:${dtStart}`,
    `DTEND:${dtEnd}`,
    `SUMMARY:Свадьба Софии & Александра`,
    `DESCRIPTION:${escapeIcs(wedding.concept)}`,
    `LOCATION:${escapeIcs(`${wedding.venueName}, ${wedding.venueAddress}`)}`,
    "BEGIN:VALARM",
    "TRIGGER:-P2D",
    "ACTION:DISPLAY",
    "DESCRIPTION:Свадьба через 2 дня — не забудьте RSVP!",
    "END:VALARM",
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
}

function toIcsLocal(d: Date): string {
  // Express as local time (no Z) so the calendar respects the venue timezone
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `T${pad(d.getHours())}${pad(d.getMinutes())}00`
  );
}

function escapeIcs(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

function CalendarIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="16" rx="1.5" />
      <path d="M3 9h18M8 3v4M16 3v4" />
      <circle cx="8" cy="14" r="0.8" fill="currentColor" />
      <circle cx="12" cy="14" r="0.8" fill="currentColor" />
      <circle cx="16" cy="14" r="0.8" fill="currentColor" />
    </svg>
  );
}

function ShareIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" />
    </svg>
  );
}
