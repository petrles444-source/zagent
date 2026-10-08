"use client";

import { useEffect, useState } from "react";
import { Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type PollData = {
  tally: { yes: number; maybe: number; no: number };
  total: number;
  sparkline: { date: string; total: number }[];
};

const OPTIONS = [
  { key: "yes", label: "Буду", cls: "border-gold/60 bg-gold/15 text-gold" },
  { key: "maybe", label: "Возможно", cls: "border-gold/30 text-ivory-soft/70" },
  { key: "no", label: "Не смогу", cls: "border-blush/30 text-blush/80" },
] as const;

export function GuestPoll() {
  const { toast } = useToast();
  const [data, setData] = useState<PollData | null>(null);
  const [voted, setVoted] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void load();
    // check cookie presence via a server round-trip is overkill; we just
    // let the API tell us the previous vote on the next poll.
  }, []);

  const load = async () => {
    try {
      const res = await fetch("/api/poll", { cache: "no-store" });
      if (res.ok) {
        const d = await res.json();
        setData(d);
      }
    } catch {
      /* ignore */
    }
  };

  const vote = async (answer: string) => {
    if (voted === answer) return; // no-op
    setSubmitting(true);
    try {
      const res = await fetch("/api/poll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
      });
      const json = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: json?.error, variant: "destructive" });
      } else {
        setVoted(answer);
        if (json.previous && json.previous !== answer) {
          toast({ title: "Голос обновлён" });
        } else if (!json.previous) {
          toast({ title: "Спасибо за голос!" });
        }
        await load();
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  if (!data) return null;

  const max = Math.max(1, ...data.sparkline.map((s) => s.total));

  return (
    <div className="card-luxe relative overflow-hidden rounded-sm p-6 sm:p-8">
      <span className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />
      <div className="flex items-center gap-2">
        <Heart className="h-4 w-4 text-gold animate-flicker" />
        <h3 className="font-playfair text-xl text-ivory">А вы придёте?</h3>
      </div>
      <p className="mt-1 font-cormorant text-sm text-ivory-soft/60">
        Быстрый опрос — покажите, что будете с нами в полночь.
      </p>

      {/* vote buttons */}
      <div className="mt-5 grid grid-cols-3 gap-2">
        {OPTIONS.map((o) => (
          <button
            key={o.key}
            onClick={() => vote(o.key)}
            disabled={submitting}
            className={cn(
              "rounded-sm border px-3 py-3 font-cormorant text-sm transition-all duration-300 disabled:opacity-50",
              voted === o.key
                ? o.cls
                : "border-gold/20 bg-night/40 text-ivory-soft/70 hover:border-gold/50 hover:text-ivory"
            )}
          >
            <span className="block font-playfair text-lg">{o.label}</span>
            <span className="mt-0.5 block text-xs tabular-nums text-gold-soft">
              {data.tally[o.key as keyof typeof data.tally]}
            </span>
          </button>
        ))}
      </div>

      {/* total + sparkline */}
      <div className="mt-5 flex items-end justify-between gap-4">
        <div>
          <p className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
            Всего голосов
          </p>
          <p className="font-playfair text-3xl text-ivory tabular-nums">{data.total}</p>
        </div>
        <div className="flex-1">
          <p className="mb-1 text-right font-playfair text-[0.6rem] uppercase tracking-luxe text-gold/60">
            за 14 дней
          </p>
          <Sparkline data={data.sparkline.map((s) => s.total)} max={max} />
        </div>
      </div>

      <span className="pointer-events-none absolute inset-x-8 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/30 to-transparent" />
    </div>
  );
}

function Sparkline({ data, max }: { data: number[]; max: number }) {
  const w = 120;
  const h = 36;
  const step = data.length > 1 ? w / (data.length - 1) : w;
  const points = data
    .map((v, i) => {
      const x = i * step;
      const y = h - (v / max) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const areaPoints = `0,${h} ${points} ${w},${h}`;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="h-9 w-full"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#c8a96a" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#c8a96a" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill="url(#spark-fill)" />
      <polyline
        points={points}
        fill="none"
        stroke="#c8a96a"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* last point dot */}
      {data.length > 0 && (
        <circle
          cx={(data.length - 1) * step}
          cy={h - (data[data.length - 1] / max) * (h - 4) - 2}
          r="2"
          fill="#e6cd92"
        />
      )}
    </svg>
  );
}
