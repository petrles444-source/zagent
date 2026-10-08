"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { SectionHeading, Heart } from "./ornaments";
import { Reveal } from "./reveal";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type Wish = {
  id: string;
  name: string;
  message: string;
  attend: string | null;
  likes: number;
  createdAt: string;
};

const LIKED_KEY = "wedding-liked-wishes";

function readLiked(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(LIKED_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

function writeLiked(set: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LIKED_KEY, JSON.stringify(Array.from(set)));
  } catch {
    /* ignore quota */
  }
}

export function Guestbook() {
  const { toast } = useToast();
  const [items, setItems] = useState<Wish[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [attend, setAttend] = useState<"yes" | "no" | "maybe" | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [liked, setLiked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [filterAttend, setFilterAttend] = useState<"all" | "yes" | "maybe" | "no">("all");
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "liked">("newest");

  const load = async () => {
    try {
      const res = await fetch("/api/guestbook", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLiked(readLiked());
    load();
  }, []);

  const toggleLike = useCallback(async (id: string) => {
    const already = liked.has(id);
    const next = new Set(liked);
    if (already) next.delete(id);
    else next.add(id);
    setLiked(next);
    writeLiked(next);

    // optimistic update
    setItems((cur) =>
      cur.map((w) =>
        w.id === id ? { ...w, likes: Math.max(0, w.likes + (already ? -1 : 1)) } : w
      )
    );

    try {
      const res = await fetch("/api/guestbook", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, delta: already ? -1 : 1 }),
      });
      if (!res.ok) {
        // revert on failure
        const revert = new Set(liked);
        if (already) revert.add(id);
        else revert.delete(id);
        setLiked(revert);
        writeLiked(revert);
        setItems((cur) =>
          cur.map((w) =>
            w.id === id ? { ...w, likes: Math.max(0, w.likes + (already ? 1 : -1)) } : w
          )
        );
        toast({ title: "Не получилось", variant: "destructive" });
      }
    } catch {
      /* network — keep optimistic */
    }
  }, [liked, toast]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matched = items.filter((w) => {
      if (filterAttend !== "all" && w.attend !== filterAttend) return false;
      if (!q) return true;
      return (
        w.name.toLowerCase().includes(q) ||
        w.message.toLowerCase().includes(q)
      );
    });
    const sorted = [...matched];
    if (sortBy === "newest") {
      sorted.sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt));
    } else if (sortBy === "oldest") {
      sorted.sort((a, b) => +new Date(a.createdAt) - +new Date(b.createdAt));
    } else if (sortBy === "liked") {
      sorted.sort((a, b) => (b.likes ?? 0) - (a.likes ?? 0));
    }
    return sorted;
  }, [items, search, filterAttend, sortBy]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast({ title: "Укажите имя", variant: "destructive" });
      return;
    }
    if (!message.trim()) {
      toast({ title: "Напишите пожелание", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/guestbook", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, message, attend: attend || undefined }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: data?.error, variant: "destructive" });
      } else {
        toast({ title: "Спасибо за тёплые слова!" });
        setName("");
        setMessage("");
        setAttend("");
        await load();
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      id="guestbook"
      className="relative overflow-hidden bg-night-soft py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Стена пожеланий"
            title="Тёплые слова"
            subtitle="Оставьте пожелание — мы перечитаем их все после полуночи, когда стихнет музыка."
          />
        </Reveal>

        <div className="mt-14 grid gap-8 lg:grid-cols-[1fr_1.3fr]">
          {/* Form */}
          <Reveal>
            <form onSubmit={submit} className="card-luxe rounded-sm p-6 sm:p-8">
              <div className="flex flex-col gap-5">
                <Field label="Ваше имя">
                  <input
                    className="input-luxe"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Как вас зовут"
                  />
                </Field>
                <Field label="Пожелание">
                  <textarea
                    rows={5}
                    className="input-luxe resize-none"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder="Пара тёплых слов для молодожёнов…"
                    maxLength={1000}
                  />
                  <span className="mt-1 text-right font-cormorant text-xs text-ivory-soft/50">
                    {message.length}/1000
                  </span>
                </Field>
                <Field label="Сможете прийти?">
                  <div className="grid grid-cols-3 gap-2">
                    {(["yes", "maybe", "no"] as const).map((v) => (
                      <button
                        type="button"
                        key={v}
                        onClick={() => setAttend((cur) => (cur === v ? "" : v))}
                        className={cn(
                          "rounded-sm border px-3 py-2.5 font-cormorant text-sm transition-all",
                          attend === v
                            ? "border-gold bg-gold/15 text-ivory"
                            : "border-gold/25 bg-night/40 text-ivory-soft/70 hover:border-gold/50"
                        )}
                      >
                        {v === "yes" ? "Буду" : v === "maybe" ? "Возможно" : "Не смогу"}
                      </button>
                    ))}
                  </div>
                </Field>
                <div className="flex flex-col items-center gap-2">
                  <div className="ornament-line text-gold">
                    <Heart className="h-3 w-3" />
                  </div>
                  <button type="submit" disabled={submitting} className="btn-luxe disabled:opacity-60">
                    {submitting ? "Отправляем…" : "Оставить пожелание"}
                  </button>
                </div>
              </div>
            </form>
          </Reveal>

          {/* Wall */}
          <Reveal delay={150}>
            <div className="relative">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
                  {filtered.length > 0
                    ? `${filtered.length} ${plural(filtered.length, ["пожелание", "пожелания", "пожеланий"])}`
                    : items.length === 0
                    ? "Пока пусто"
                    : "Ничего не найдено"}
                </span>
                <span className="font-cormorant text-sm text-ivory-soft/60">обновлено только что</span>
              </div>

              {/* search + filter */}
              {items.length > 0 && (
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <div className="relative flex-1 min-w-[12rem]">
                    <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gold/50" />
                    <input
                      className="input-luxe py-2 pl-9 text-sm"
                      placeholder="Искать по имени или тексту…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      aria-label="Поиск по пожеланиям"
                    />
                    {search ? (
                      <button
                        onClick={() => setSearch("")}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gold/60 hover:text-gold"
                        aria-label="Очистить"
                      >
                        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
                          <path d="M6 6l12 12M18 6L6 18" />
                        </svg>
                      </button>
                    ) : null}
                  </div>
                  <div className="flex gap-1">
                    {(["all", "yes", "maybe", "no"] as const).map((f) => (
                      <button
                        key={f}
                        onClick={() => setFilterAttend(f)}
                        className={cn(
                          "rounded-sm border px-2.5 py-1.5 font-cormorant text-xs transition-all",
                          filterAttend === f
                            ? "border-gold bg-gold/15 text-gold"
                            : "border-gold/20 text-ivory-soft/60 hover:border-gold/40 hover:text-ivory"
                        )}
                      >
                        {f === "all" ? "Все" : f === "yes" ? "Будут" : f === "maybe" ? "?" : "Не смогут"}
                      </button>
                    ))}
                  </div>
                  {/* sort control */}
                  <div className="ml-auto flex items-center gap-1.5">
                    <span className="font-cormorant text-xs text-ivory-soft/40">сортировка:</span>
                    <div className="flex gap-1">
                      {([
                        ["newest", "Новые"],
                        ["oldest", "Старые"],
                        ["liked", "♥ Лайки"],
                      ] as const).map(([key, label]) => (
                        <button
                          key={key}
                          onClick={() => setSortBy(key)}
                          className={cn(
                            "rounded-sm border px-2 py-1 font-cormorant text-xs transition-all",
                            sortBy === key
                              ? "border-gold bg-gold/15 text-gold"
                              : "border-gold/15 text-ivory-soft/50 hover:border-gold/40 hover:text-ivory"
                          )}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="luxe-scroll max-h-[34rem] space-y-4 overflow-y-auto pr-2">
                {loading ? (
                  <SkeletonList />
                ) : filtered.length === 0 ? (
                  items.length === 0 ? (
                    <EmptyState />
                  ) : (
                    <div className="card-luxe rounded-sm p-8 text-center">
                      <Heart className="mx-auto h-5 w-5 text-gold/40" />
                      <p className="mt-2 font-cormorant text-base text-ivory-soft/60">
                        Ничего не найдено по запросу «{search}»
                      </p>
                    </div>
                  )
                ) : (
                  filtered.map((w) => (
                    <WishCard
                      key={w.id}
                      wish={w}
                      liked={liked.has(w.id)}
                      onToggleLike={() => toggleLike(w.id)}
                    />
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

function WishCard({
  wish,
  liked,
  onToggleLike,
}: {
  wish: Wish;
  liked: boolean;
  onToggleLike: () => void;
}) {
  const date = new Date(wish.createdAt);
  const dateStr = date.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const initial = wish.name.trim().charAt(0).toUpperCase() || "♥";
  return (
    <article className="card-luxe group relative rounded-sm p-5 transition-all hover:border-gold/40">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-gold/40 font-playfair text-lg text-gold">
          {initial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="font-playfair text-lg text-ivory">{wish.name}</h4>
            <time className="font-cormorant text-xs text-ivory-soft/50">{dateStr}</time>
          </div>
          {wish.attend ? (
            <span className="mt-0.5 inline-block font-cormorant text-xs text-gold/80">
              {wish.attend === "yes" ? "· будет на свадьбе" : wish.attend === "maybe" ? "· возможно будет" : "· не сможет прийти"}
            </span>
          ) : null}
          <p className="mt-2 font-cormorant text-base leading-relaxed text-ivory-soft/85 whitespace-pre-wrap">
            {wish.message}
          </p>

          {/* Like button */}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={onToggleLike}
              aria-pressed={liked}
              aria-label={liked ? "Убрать лайк" : "Поставить лайк"}
              className={cn(
                "group/like flex items-center gap-1.5 rounded-full border px-3 py-1 transition-all duration-300",
                liked
                  ? "border-gold/60 bg-gold/15 text-gold"
                  : "border-gold/20 bg-night/40 text-ivory-soft/60 hover:border-gold/50 hover:text-gold"
              )}
            >
              <Heart
                className={cn(
                  "h-3.5 w-3.5 transition-transform duration-300",
                  liked ? "scale-110 animate-flicker" : "group-hover/like:scale-110"
                )}
                filled={liked}
              />
              <span className="font-cormorant text-sm tabular-nums">
                {wish.likes}
              </span>
            </button>
            <span className="font-cormorant text-xs text-ivory-soft/40">
              {liked ? "вам понравилось" : "нравится"}
            </span>
          </div>
        </div>
      </div>
      <Heart className="absolute right-3 top-3 h-3 w-3 text-gold/25" />
    </article>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
        {label}
      </span>
      {children}
    </label>
  );
}

function EmptyState() {
  return (
    <div className="card-luxe rounded-sm p-10 text-center">
      <Heart className="mx-auto h-6 w-6 text-gold/60" />
      <p className="mt-3 font-cormorant text-lg text-ivory-soft/70">
        Будьте первым, кто оставит пожелание
      </p>
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="card-luxe rounded-sm p-5">
          <div className="flex gap-4">
            <div className="h-11 w-11 rounded-full bg-gold/10" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-1/3 bg-gold/10" />
              <div className="h-3 w-full bg-gold/5" />
              <div className="h-3 w-4/5 bg-gold/5" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function plural(n: number, forms: [string, string, string]) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}
