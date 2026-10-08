"use client";

import { useEffect, useState } from "react";
import { SectionHeading, Heart, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { wedding } from "@/lib/wedding-config";

type Song = {
  id: string;
  name: string;
  title: string;
  artist: string | null;
  nowPlaying: boolean;
  createdAt: string;
};

/** First-dance window: 03:00–03:20 on the wedding night. */
const FIRST_DANCE_START = new Date(wedding.dateISO).getTime() + 3 * 60 * 60 * 1000;
const FIRST_DANCE_END = FIRST_DANCE_START + 20 * 60 * 1000;

function isFirstDanceWindow(): boolean {
  const now = Date.now();
  return now >= FIRST_DANCE_START && now <= FIRST_DANCE_END;
}

export function SongRequests() {
  const { toast } = useToast();
  const [songs, setSongs] = useState<Song[]>([]);
  const [firstDance, setFirstDance] = useState(false);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void load();
    setFirstDance(isFirstDanceWindow());
    // poll for "now playing" changes + first-dance window (live on the night)
    const id = setInterval(() => {
      void load();
      setFirstDance(isFirstDanceWindow());
    }, 10000);
    return () => clearInterval(id);
  }, []);

  const load = async () => {
    try {
      const res = await fetch("/api/songs", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setSongs(data.items ?? []);
      }
    } catch {
      /* ignore */
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !title.trim()) {
      toast({ title: "Укажите имя и название песни", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/songs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, title, artist }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: data?.error, variant: "destructive" });
      } else {
        toast({ title: "Песня добавлена в плейлист вечера!" });
        setName("");
        setTitle("");
        setArtist("");
        await load();
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="relative overflow-hidden bg-night py-24 sm:py-28">
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-5xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Танцпол"
            title="Закажите песню"
            subtitle="Что должно звучать в полночь? Предложите трек — и, возможно, именно под него мы станцим наш первый танец."
          />
        </Reveal>

        <div className="mt-12 grid gap-8 md:grid-cols-2">
          <Reveal>
            <form onSubmit={submit} className="card-luxe rounded-sm p-6 sm:p-8">
              <div className="flex flex-col gap-5">
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">Ваше имя</span>
                  <input className="input-luxe" value={name} onChange={(e) => setName(e.target.value)} placeholder="Как вас зовут" />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">Песня *</span>
                  <input className="input-luxe" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Название трека" />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">Исполнитель</span>
                  <input className="input-luxe" value={artist} onChange={(e) => setArtist(e.target.value)} placeholder="Имя артиста (необязательно)" />
                </label>
                <div className="flex justify-center">
                  <button type="submit" disabled={submitting} className="btn-luxe disabled:opacity-60">
                    {submitting ? "Добавляем…" : "Заказать"}
                  </button>
                </div>
              </div>
            </form>
          </Reveal>

          <Reveal delay={150}>
            <div className="card-luxe rounded-sm p-6 sm:p-8">
              <div className="mb-4 flex items-center gap-3">
                <Sprig className="h-5 w-5 text-gold/70" />
                <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
                  Плейлист вечера
                </span>
              </div>
              <div className="luxe-scroll max-h-[26rem] space-y-2 overflow-y-auto pr-1">
                {songs.length === 0 ? (
                  <p className="py-8 text-center font-cormorant text-base text-ivory-soft/60">
                    Пока никто не предложил трек. Будьте первым!
                  </p>
                ) : (
                  songs.map((s, i) => (
                    <div
                      key={s.id}
                      className={cn(
                        "group flex items-center gap-3 rounded-sm border px-4 py-3 transition-colors",
                        s.nowPlaying
                          ? "border-gold/50 bg-gold/10 shadow-[0_0_20px_-4px_rgba(200,169,106,0.4)]"
                          : "border-gold/12 bg-night/40 hover:border-gold/30"
                      )}
                    >
                      {/* spinning vinyl (spins faster when now playing) */}
                      <Vinyl index={i} spinning={s.nowPlaying} />
                      <div className="min-w-0 flex-1">
                        <p className={cn(
                          "truncate font-cormorant text-base",
                          s.nowPlaying ? "text-ivory" : "text-ivory"
                        )}>
                          {s.title}
                        </p>
                        <p className="truncate font-cormorant text-sm text-ivory-soft/60">
                          {s.artist || "—"} · от {s.name}
                        </p>
                      </div>
                      {s.nowPlaying ? (
                        <NowPlayingBadge firstDance={firstDance} />
                      ) : (
                        <Heart className="h-3 w-3 text-gold/40 transition-transform group-hover:scale-125" />
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Vinyl({ index, spinning = false }: { index: number; spinning?: boolean }) {
  // alternate rotation direction per track for visual variety;
  // spin faster (1.5s) when this track is "now playing"
  const dir = index % 2 === 0 ? "normal" : "reverse";
  const duration = spinning ? "1.5s" : "4s";
  return (
    <div
      className={cn("relative h-10 w-10 shrink-0", spinning && "drop-shadow-[0_0_8px_rgba(200,169,106,0.6)]")}
      style={{ animation: `vinyl-spin ${duration} linear ${dir} infinite` }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 40 40" className="h-full w-full">
        <defs>
          <radialGradient id={`vin-${index}`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#0b0908" />
            <stop offset="45%" stopColor="#1a1410" />
            <stop offset="80%" stopColor="#0b0908" />
            <stop offset="100%" stopColor="#211a15" />
          </radialGradient>
        </defs>
        {/* record */}
        <circle cx="20" cy="20" r="18" fill={`url(#vin-${index})`} stroke="#c8a96a" strokeWidth="0.4" />
        {/* grooves */}
        <circle cx="20" cy="20" r="14" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.3" />
        <circle cx="20" cy="20" r="11" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.25" />
        <circle cx="20" cy="20" r="8" fill="none" stroke="#c8a96a" strokeWidth="0.2" opacity="0.2" />
        {/* center label */}
        <circle cx="20" cy="20" r="5.5" fill="#c8a96a" />
        <circle cx="20" cy="20" r="4.5" fill="none" stroke="#0b0908" strokeWidth="0.3" />
        {/* spindle hole */}
        <circle cx="20" cy="20" r="1" fill="#0b0908" />
        {/* highlight reflection */}
        <path d="M14 8 A 14 14 0 0 1 26 8" fill="none" stroke="#f4ece0" strokeWidth="0.5" opacity="0.15" />
      </svg>
    </div>
  );
}

/** Animated "NOW PLAYING" badge with equalizer bars.
 *  When `firstDance` is true, shows "Первый танец" with a heart accent. */
function NowPlayingBadge({ firstDance = false }: { firstDance?: boolean }) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1",
        firstDance
          ? "border-blush/50 bg-blush/10 shadow-[0_0_14px_-2px_rgba(231,201,192,0.4)]"
          : "border-gold/40 bg-gold/10"
      )}
    >
      {firstDance ? (
        <Heart className="h-2.5 w-2.5 text-blush animate-flicker" filled />
      ) : null}
      {/* equalizer bars */}
      <span className="flex h-3 items-end gap-[2px]">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={firstDance ? "w-[2px] bg-blush" : "w-[2px] bg-gold"}
            style={{
              height: "100%",
              animation: `eq-bar 0.8s ease-in-out ${i * 0.15}s infinite alternate`,
              transformOrigin: "bottom",
            }}
          />
        ))}
      </span>
      <span
        className={cn(
          "font-playfair text-[0.55rem] uppercase tracking-luxe",
          firstDance ? "text-blush" : "text-gold"
        )}
      >
        {firstDance ? "первый танец" : "сейчас"}
      </span>
    </div>
  );
}
