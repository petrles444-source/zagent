"use client";

import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { wedding } from "@/lib/wedding-config";
import { Heart, Monogram, Sprig } from "@/components/wedding/ornaments";
import { cn } from "@/lib/utils";

type Rsvp = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  attending: "yes" | "no" | "maybe";
  guests: number;
  meal: string | null;
  drink: string | null;
  message: string | null;
  createdAt: string;
};
type Wish = {
  id: string;
  name: string;
  message: string;
  attend: string | null;
  likes: number;
  createdAt: string;
};
type Song = {
  id: string;
  name: string;
  title: string;
  artist: string | null;
  nowPlaying: boolean;
  createdAt: string;
};
type PhotoItem = {
  id: string;
  guestName: string;
  caption: string | null;
  image: string;
  approved: boolean;
  createdAt: string;
};
type Summary = {
  stats: {
    rsvp: { yes: number; no: number; maybe: number; totalGuests: number; responses: number };
    guestbook: { count: number; likes: number };
    songs: { count: number };
  };
  breakdowns: { meal: Record<string, number>; drink: Record<string, number> };
  rsvps: Rsvp[];
  guestbook: Wish[];
  songs: Song[];
  token: string;
};

const MEAL_LABELS: Record<string, string> = {
  regular: "Основное",
  vegetarian: "Вегетарианское",
  vegan: "Веганское",
  kids: "Детское",
  "—": "—",
};
const DRINK_LABELS: Record<string, string> = {
  wine: "Вино",
  champagne: "Шампанское",
  strong: "Крепкое",
  none: "Безалкогольное",
  "—": "—",
};

export default function AdminPage() {
  const { toast } = useToast();
  const [token, setToken] = useState("");
  const [authed, setAuthed] = useState(false);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"rsvp" | "guestbook" | "songs" | "photos">("rsvp");
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [photosLoading, setPhotosLoading] = useState(false);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/summary?token=${encodeURIComponent(t)}`);
      const json = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: json?.error, variant: "destructive" });
        setAuthed(false);
      } else {
        setData(json);
        setAuthed(true);
        sessionStorage.setItem("admin-token", t);
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  // restore token from sessionStorage so refreshes don't log out
  useEffect(() => {
    const saved = sessionStorage.getItem("admin-token");
    if (saved) {
      setToken(saved);
      void load(saved);
    }
  }, [load]);

  const onLogin = (e: React.FormEvent) => {
    e.preventDefault();
    void load(token);
  };

  const onLogout = () => {
    sessionStorage.removeItem("admin-token");
    setAuthed(false);
    setData(null);
    setToken("");
  };

  // ---- photo moderation ----
  const loadPhotos = useCallback(async () => {
    setPhotosLoading(true);
    try {
      const res = await fetch(`/api/photos?pending=1`, { cache: "no-store" });
      if (res.ok) {
        const d = await res.json();
        setPhotos(d.items ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setPhotosLoading(false);
    }
  }, []);

  const photoAction = useCallback(
    async (id: string, action: "approve" | "unapprove" | "delete") => {
      const t = sessionStorage.getItem("admin-token") ?? "";
      try {
        const res = await fetch(
          `/api/admin/photos?token=${encodeURIComponent(t)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id, action }),
          }
        );
        if (res.ok) {
          if (action === "delete") {
            setPhotos((cur) => cur.filter((p) => p.id !== id));
          } else {
            setPhotos((cur) =>
              cur.map((p) =>
                p.id === id ? { ...p, approved: action === "approve" } : p
              )
            );
          }
        }
      } catch {
        toast({ title: "Ошибка", variant: "destructive" });
      }
    },
    [toast]
  );

  // ---- song "now playing" control ----
  const songAction = useCallback(
    async (id: string, action: "play" | "stop") => {
      const t = sessionStorage.getItem("admin-token") ?? "";
      try {
        const res = await fetch(
          `/api/admin/songs?token=${encodeURIComponent(t)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id, action }),
          }
        );
        if (res.ok) {
          const json = await res.json();
          // update local song list: clear all nowPlaying, set the chosen one
          setData((cur) =>
            cur
              ? {
                  ...cur,
                  songs: cur.songs.map((s) => ({
                    ...s,
                    nowPlaying: s.id === id ? action === "play" : false,
                  })),
                }
              : cur
          );
          void json;
        }
      } catch {
        toast({ title: "Ошибка", variant: "destructive" });
      }
    },
    [toast]
  );

  // load photos when the photos tab is opened
  useEffect(() => {
    if (authed && tab === "photos" && photos.length === 0) {
      void loadPhotos();
    }
  }, [authed, tab, photos.length, loadPhotos]);

  if (!authed) {
    return (
      <div className="relative flex min-h-screen flex-col items-center justify-center bg-night px-6 text-center">
        <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
        <div className="absolute inset-0 bg-radial-gold opacity-50" aria-hidden="true" />
        <div className="relative w-full max-w-sm">
          <Monogram
            left={wedding.brideInitials}
            right={wedding.groomInitials}
            className="mx-auto h-20 w-20 text-gold"
          />
          <h1 className="mt-6 font-playfair text-3xl text-ivory">Кабинет организатора</h1>
          <div className="mx-auto my-5 ornament-line text-gold">
            <Heart className="h-3 w-3" />
          </div>
          <p className="font-cormorant text-base text-ivory-soft/70">
            Введите пароль для доступа к ответам RSVP, пожеланиям и плейлисту.
          </p>
          <form onSubmit={onLogin} className="mt-8 flex flex-col gap-4">
            <input
              type="password"
              className="input-luxe"
              placeholder="Пароль администратора"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
            />
            <button type="submit" disabled={loading || !token} className="btn-luxe disabled:opacity-60">
              {loading ? "Проверяем…" : "Войти"}
            </button>
          </form>
          <a
            href="/"
            className="mt-6 inline-block font-cormorant text-sm text-gold/70 hover:text-gold"
          >
            ← Вернуться на сайт
          </a>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const exportUrl = (type: "rsvp" | "guestbook" | "songs") =>
    `/api/admin/export?token=${encodeURIComponent(data.token)}&type=${type}`;

  return (
    <div className="min-h-screen bg-night text-ivory">
      <div className="bg-grain pointer-events-none fixed inset-0 opacity-30" aria-hidden="true" />
      <header className="sticky top-0 z-10 border-b border-gold/15 bg-night/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Heart className="h-4 w-4 text-gold" filled />
            <span className="font-playfair text-sm uppercase tracking-wide-2">
              Кабинет · София & Александр
            </span>
          </div>
          <div className="flex items-center gap-4">
            <a href="/" className="font-cormorant text-sm text-gold/70 hover:text-gold">
              ← Сайт
            </a>
            <button onClick={onLogout} className="font-cormorant text-sm text-ivory-soft/70 hover:text-blush">
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-6xl px-6 py-10">
        {/* Stats overview */}
        <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Подтвердили" value={data.stats.rsvp.yes} accent />
          <StatCard label="Всего гостей" value={data.stats.rsvp.totalGuests} />
          <StatCard label="Пожеланий" value={data.stats.guestbook.count} />
          <StatCard label="Песен" value={data.stats.songs.count} />
        </section>

        {/* Breakdowns */}
        <section className="mt-8 grid gap-4 md:grid-cols-2">
          <BreakdownCard
            title="Меню"
            data={data.breakdowns.meal}
            labels={MEAL_LABELS}
            total={data.stats.rsvp.responses}
          />
          <BreakdownCard
            title="Напитки"
            data={data.breakdowns.drink}
            labels={DRINK_LABELS}
            total={data.stats.rsvp.responses}
          />
        </section>

        {/* Tabs */}
        <section className="mt-10">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gold/15 pb-4">
            <div className="flex gap-2">
              {([
                ["rsvp", `RSVP (${data.rsvps.length})`],
                ["guestbook", `Пожелания (${data.guestbook.length})`],
                ["songs", `Песни (${data.songs.length})`],
                ["photos", "Фото"],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={cn(
                    "rounded-sm border px-4 py-2 font-playfair text-xs uppercase tracking-wide-2 transition-all",
                    tab === key
                      ? "border-gold bg-gold/15 text-gold"
                      : "border-gold/20 text-ivory-soft/60 hover:border-gold/40 hover:text-ivory"
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab !== "photos" && (
              <a
                href={exportUrl(tab as "rsvp" | "guestbook" | "songs")}
                className="btn-ghost-luxe"
                download
              >
                ↓ Экспорт CSV
              </a>
            )}
          </div>

          <div className="mt-6">
            {tab === "rsvp" && <RsvpTable items={data.rsvps} />}
            {tab === "guestbook" && <GuestbookList items={data.guestbook} />}
            {tab === "songs" && <SongList items={data.songs} onAction={songAction} />}
            {tab === "photos" && (
              <PhotoModeration
                items={photos}
                loading={photosLoading}
                onAction={photoAction}
                onReload={loadPhotos}
              />
            )}
          </div>
        </section>

        <div className="mt-12 flex items-center justify-center gap-3 text-gold">
          <Sprig className="h-5 w-5" />
          <span className="font-cormorant text-sm text-ivory-soft/50">
            Кабинет организатора · обновлено {new Date().toLocaleTimeString("ru-RU")}
          </span>
          <Sprig className="h-5 w-5 -scale-x-100" />
        </div>
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div className="card-luxe rounded-sm p-5 text-center">
      <div
        className={cn(
          "font-playfair text-4xl tabular-nums sm:text-5xl",
          accent ? "text-gold-gradient" : "text-ivory"
        )}
      >
        {value}
      </div>
      <div className="mt-1 font-playfair text-[0.64rem] uppercase tracking-luxe text-ivory-soft/70">
        {label}
      </div>
    </div>
  );
}

function BreakdownCard({
  title,
  data,
  labels,
  total,
}: {
  title: string;
  data: Record<string, number>;
  labels: Record<string, string>;
  total: number;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div className="card-luxe rounded-sm p-6">
      <h3 className="font-playfair text-lg text-ivory">{title}</h3>
      <div className="mt-4 space-y-3">
        {entries.length === 0 ? (
          <p className="font-cormorant text-sm text-ivory-soft/50">Пока нет данных</p>
        ) : (
          entries.map(([key, count]) => {
            const pct = total > 0 ? Math.round((count / total) * 100) : 0;
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="w-40 shrink-0 font-cormorant text-sm text-ivory-soft/80">
                  {labels[key] ?? key}
                </span>
                <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-gold/10">
                  <div
                    className="h-full bg-gradient-to-r from-gold-soft via-gold to-gold-soft transition-all duration-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right font-cormorant text-sm text-gold-soft tabular-nums">
                  {count} · {pct}%
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function RsvpTable({ items }: { items: Rsvp[] }) {
  if (items.length === 0) return <Empty msg="Пока ни одного ответа" />;
  return (
    <div className="luxe-scroll max-h-[36rem] overflow-auto rounded-sm border border-gold/15">
      <table className="w-full border-collapse text-left">
        <thead className="sticky top-0 bg-night-soft">
          <tr className="text-[0.66rem] uppercase tracking-wide-2 text-gold">
            <th className="p-3">Имя</th>
            <th className="p-3">Контакт</th>
            <th className="p-3">Придёт</th>
            <th className="p-3 text-center">Гостей</th>
            <th className="p-3">Меню</th>
            <th className="p-3">Напиток</th>
            <th className="p-3">Сообщение</th>
            <th className="p-3">Дата</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id} className="border-t border-gold/10 text-sm hover:bg-night-soft/60">
              <td className="p-3 font-playfair text-ivory">{r.name}</td>
              <td className="p-3 font-cormorant text-ivory-soft/70">
                <div>{r.email ?? "—"}</div>
                <div className="text-xs">{r.phone ?? ""}</div>
              </td>
              <td className="p-3">
                <AttendBadge value={r.attending} />
              </td>
              <td className="p-3 text-center font-cormorant text-gold-soft tabular-nums">{r.guests}</td>
              <td className="p-3 font-cormorant text-ivory-soft/70">{MEAL_LABELS[r.meal ?? "—"] ?? r.meal}</td>
              <td className="p-3 font-cormorant text-ivory-soft/70">{DRINK_LABELS[r.drink ?? "—"] ?? r.drink}</td>
              <td className="max-w-xs p-3 font-cormorant text-ivory-soft/70">
                <span className="line-clamp-2">{r.message ?? "—"}</span>
              </td>
              <td className="p-3 font-cormorant text-xs text-ivory-soft/50">
                {new Date(r.createdAt).toLocaleDateString("ru-RU")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GuestbookList({ items }: { items: Wish[] }) {
  if (items.length === 0) return <Empty msg="Пока ни одного пожелания" />;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map((w) => (
        <article key={w.id} className="card-luxe rounded-sm p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h4 className="font-playfair text-base text-ivory">{w.name}</h4>
            <span className="font-cormorant text-xs text-ivory-soft/50">
              {new Date(w.createdAt).toLocaleDateString("ru-RU")}
            </span>
          </div>
          {w.attend ? (
            <span className="mt-1 inline-block font-cormorant text-xs text-gold/70">
              {w.attend === "yes" ? "· будет" : w.attend === "maybe" ? "· возможно" : "· не сможет"}
            </span>
          ) : null}
          <p className="mt-2 font-cormorant text-sm leading-relaxed text-ivory-soft/80">{w.message}</p>
          <div className="mt-3 flex items-center gap-2">
            <Heart className="h-3 w-3 text-gold/70" filled />
            <span className="font-cormorant text-xs text-gold/70 tabular-nums">{w.likes ?? 0}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function SongList({
  items,
  onAction,
}: {
  items: Song[];
  onAction: (id: string, action: "play" | "stop") => void;
}) {
  if (items.length === 0) return <Empty msg="Пока ни одной песни" />;
  return (
    <ol className="space-y-2">
      {items.map((s, i) => (
        <li
          key={s.id}
          className={cn(
            "card-luxe flex items-center gap-4 rounded-sm p-4",
            s.nowPlaying && "border-gold/50 bg-gold/5"
          )}
        >
          <span className="font-playfair text-2xl text-gold/70 tabular-nums">
            {String(i + 1).padStart(2, "0")}
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-playfair text-base text-ivory">{s.title}</p>
            <p className="font-cormorant text-sm text-ivory-soft/60">
              {s.artist || "—"} · от {s.name}
            </p>
          </div>
          {s.nowPlaying ? (
            <span className="flex items-center gap-1.5 rounded-full border border-gold/50 bg-gold/15 px-2.5 py-1 font-playfair text-[0.55rem] uppercase tracking-luxe text-gold">
              <span className="flex h-3 items-end gap-[2px]">
                {[0, 1, 2, 3].map((k) => (
                  <span
                    key={k}
                    className="w-[2px] bg-gold"
                    style={{
                      height: "100%",
                      animation: `eq-bar 0.8s ease-in-out ${k * 0.15}s infinite alternate`,
                      transformOrigin: "bottom",
                    }}
                  />
                ))}
              </span>
              играет
            </span>
          ) : null}
          <button
            onClick={() => onAction(s.id, s.nowPlaying ? "stop" : "play")}
            className={cn(
              "rounded-sm border px-2.5 py-1 font-cormorant text-[0.7rem] transition-all",
              s.nowPlaying
                ? "border-gold/30 text-ivory-soft/60 hover:border-gold/50"
                : "border-gold/50 bg-gold/15 text-gold hover:bg-gold/25"
            )}
          >
            {s.nowPlaying ? "Стоп" : "▶ Играть"}
          </button>
          <span className="font-cormorant text-xs text-ivory-soft/50">
            {new Date(s.createdAt).toLocaleDateString("ru-RU")}
          </span>
        </li>
      ))}
    </ol>
  );
}

function AttendBadge({ value }: { value: "yes" | "no" | "maybe" }) {
  const cfg = {
    yes: { label: "Да", cls: "border-gold/50 bg-gold/15 text-gold" },
    no: { label: "Нет", cls: "border-blush/40 bg-blush/10 text-blush" },
    maybe: { label: "Возможно", cls: "border-gold/30 text-ivory-soft/70" },
  }[value];
  return (
    <span className={cn("inline-block rounded-full border px-3 py-0.5 font-cormorant text-xs", cfg.cls)}>
      {cfg.label}
    </span>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="card-luxe rounded-sm p-10 text-center">
      <Heart className="mx-auto h-6 w-6 text-gold/50" />
      <p className="mt-3 font-cormorant text-base text-ivory-soft/60">{msg}</p>
    </div>
  );
}

function PhotoModeration({
  items,
  loading,
  onAction,
  onReload,
}: {
  items: PhotoItem[];
  loading: boolean;
  onAction: (id: string, action: "approve" | "unapprove" | "delete") => void;
  onReload: () => void;
}) {
  const pending = items.filter((p) => !p.approved);
  const approved = items.filter((p) => p.approved);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="font-cormorant text-sm text-ivory-soft/60">
          {pending.length > 0
            ? `${pending.length} ${plural(pending.length, ["фото ждёт", "фото ждут", "фото ждут"])} проверки`
            : "Нет фото на модерации"}
        </p>
        <button onClick={onReload} className="font-cormorant text-sm text-gold/70 hover:text-gold">
          ↻ Обновить
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="aspect-square animate-pulse rounded-sm border border-gold/10 bg-gold/5" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Empty msg="Пока ни одного фото" />
      ) : (
        <>
          {pending.length > 0 && (
            <div className="mb-8">
              <h4 className="mb-3 font-playfair text-sm uppercase tracking-wide-2 text-blush">
                На проверке
              </h4>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {pending.map((p) => (
                  <PhotoModerationCard key={p.id} photo={p} onAction={onAction} />
                ))}
              </div>
            </div>
          )}
          {approved.length > 0 && (
            <div>
              <h4 className="mb-3 font-playfair text-sm uppercase tracking-wide-2 text-gold">
                Одобренные ({approved.length})
              </h4>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {approved.map((p) => (
                  <PhotoModerationCard key={p.id} photo={p} onAction={onAction} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PhotoModerationCard({
  photo,
  onAction,
}: {
  photo: PhotoItem;
  onAction: (id: string, action: "approve" | "unapprove" | "delete") => void;
}) {
  return (
    <div className="card-luxe overflow-hidden rounded-sm">
      <div className="relative aspect-square w-full overflow-hidden">
        <img
          src={photo.image}
          alt={photo.caption ?? `Фото от ${photo.guestName}`}
          className="h-full w-full object-cover"
        />
        {photo.approved ? (
          <span className="absolute left-2 top-2 rounded-full border border-gold/50 bg-night/80 px-2 py-0.5 font-playfair text-[0.6rem] uppercase tracking-luxe text-gold">
            ✓ Одобрено
          </span>
        ) : (
          <span className="absolute left-2 top-2 rounded-full border border-blush/50 bg-night/80 px-2 py-0.5 font-playfair text-[0.6rem] uppercase tracking-luxe text-blush">
            Ожидает
          </span>
        )}
      </div>
      <div className="p-3">
        <p className="truncate font-playfair text-xs text-ivory">{photo.guestName}</p>
        {photo.caption ? (
          <p className="truncate font-cormorant text-[0.7rem] text-ivory-soft/60">
            {photo.caption}
          </p>
        ) : null}
        <div className="mt-2 flex gap-1">
          <button
            onClick={() => onAction(photo.id, photo.approved ? "unapprove" : "approve")}
            className={cn(
              "flex-1 rounded-sm border px-2 py-1 font-cormorant text-[0.7rem] transition-all",
              photo.approved
                ? "border-gold/30 text-ivory-soft/60 hover:border-gold/50"
                : "border-gold/50 bg-gold/15 text-gold hover:bg-gold/25"
            )}
          >
            {photo.approved ? "Скрыть" : "✓ Одобрить"}
          </button>
          <button
            onClick={() => onAction(photo.id, "delete")}
            className="rounded-sm border border-blush/30 px-2 py-1 font-cormorant text-[0.7rem] text-blush/70 transition-all hover:border-blush/60 hover:bg-blush/10"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return forms[1];
  return forms[2];
}
