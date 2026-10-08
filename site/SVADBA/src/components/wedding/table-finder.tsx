"use client";

import { useMemo, useState } from "react";
import { wedding } from "@/lib/wedding-config";
import { Heart, SectionHeading, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

type Match = {
  tableId: number;
  tableName: string;
  subtitle: string;
  guest: string;
  seatMates: string[];
  tableGuests: string[];
} | null;

type TableSummary = {
  id: number;
  name: string;
  subtitle: string;
  total: number;
};

export function TableFinder() {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [match, setMatch] = useState<Match>(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [allTables] = useState<TableSummary[]>(
    () =>
      wedding.tables.map((t) => ({
        id: t.id,
        name: t.name,
        subtitle: t.subtitle,
        total: t.guests.length,
      }))
  );

  const suggestions = useMemo(() => {
    // flat sample of guest surnames for quick pick
    const surnames = wedding.tables.flatMap((t) => t.guests);
    return Array.from(new Set(surnames)).slice(0, 8);
  }, []);

  const search = async (q: string) => {
    const term = q.trim();
    if (term.length < 2) {
      toast({ title: "Введите минимум 2 буквы", variant: "destructive" });
      return;
    }
    setLoading(true);
    setSearched(true);
    try {
      const res = await fetch(`/api/tables?q=${encodeURIComponent(term)}`);
      const data = await res.json();
      setMatch(data.match ?? null);
      if (!data.match) {
        toast({
          title: "Не нашли вас",
          description:
            "Проверьте написание или обратитесь к организаторам при входе — мы обязательно поможем.",
        });
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <section
      id="tables"
      className="relative overflow-hidden bg-night py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-cover bg-center opacity-[0.08]"
        style={{ backgroundImage: "url(/wedding/flowers.png)" }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-5xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Где вас ждут"
            title="Найдите свой стол"
            subtitle="Введите вашу фамилию — и мы покажем, за каким цветочным столом вы сидите и с кем разделите этот вечер."
          />
        </Reveal>

        <Reveal delay={120} className="mt-12">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              search(query);
            }}
            className="mx-auto flex max-w-xl flex-col items-stretch gap-3 sm:flex-row"
          >
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gold/60" />
              <input
                className="input-luxe pl-12"
                placeholder="Ваша фамилия…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Поиск стола по фамилии"
              />
            </div>
            <button type="submit" disabled={loading} className="btn-luxe disabled:opacity-60">
              {loading ? "Ищем…" : "Найти стол"}
            </button>
          </form>

          {/* quick picks */}
          <div className="mx-auto mt-4 flex max-w-xl flex-wrap items-center justify-center gap-2">
            <span className="font-cormorant text-sm text-ivory-soft/50">Например:</span>
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  setQuery(s);
                  search(s);
                }}
                className="rounded-full border border-gold/25 px-3 py-1 font-cormorant text-sm text-ivory-soft/80 transition-colors hover:border-gold/60 hover:text-gold"
              >
                {s}
              </button>
            ))}
          </div>
        </Reveal>

        {/* Result */}
        {searched && (
          <Reveal delay={80} className="mt-10">
            {match ? (
              <TableResult match={match} />
            ) : (
              <div className="mx-auto max-w-xl card-luxe rounded-sm p-8 text-center">
                <Heart className="mx-auto h-6 w-6 text-gold/60" />
                <p className="mt-3 font-playfair text-xl text-ivory">
                  Вас пока нет в списке
                </p>
                <p className="mt-2 font-cormorant text-base text-ivory-soft/70">
                  Не переживайте — организаторы при входе помогут найти ваш стол.
                  Возможно, фамилия записана иначе.
                </p>
              </div>
            )}
          </Reveal>
        )}

        {/* Browse all tables */}
        <Reveal delay={150} className="mt-14">
          <div className="ornament-line mb-6 text-gold">
            <Sprig className="h-5 w-5" />
          </div>
          <div className="flex items-center justify-center gap-3">
            <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
              Все столы вечера
            </span>
          </div>
          <div className="luxe-scroll mt-5 grid max-h-[22rem] gap-3 overflow-y-auto pr-2 sm:grid-cols-2 lg:grid-cols-3">
            {allTables.map((t) => (
              <button
                key={t.id}
                onClick={() => {
                  const table = wedding.tables.find((x) => x.id === t.id);
                  if (table) {
                    setMatch({
                      tableId: table.id,
                      tableName: table.name,
                      subtitle: table.subtitle,
                      guest: table.guests[0],
                      seatMates: table.guests.slice(1),
                      tableGuests: table.guests,
                    });
                    setSearched(true);
                    document
                      .getElementById("tables")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }
                }}
                className={cn(
                  "group card-luxe flex items-center gap-4 rounded-sm p-4 text-left transition-all hover:-translate-y-0.5 hover:border-gold/40",
                  match?.tableId === t.id && "border-gold/50 ring-1 ring-gold/20"
                )}
              >
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-gold/40 font-playfair text-lg text-gold">
                  {t.id}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-playfair text-lg text-ivory">{t.name}</p>
                  <p className="font-cormorant text-sm text-ivory-soft/60">
                    {t.subtitle}
                  </p>
                </div>
                <span className="font-cormorant text-xs text-gold/70">
                  {t.total} {pluralGuests(t.total)}
                </span>
              </button>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function TableResult({ match }: { match: NonNullable<Match> }) {
  return (
    <div className="mx-auto max-w-2xl">
      <div className="card-luxe relative overflow-hidden rounded-sm p-8 text-center sm:p-10">
        {/* glow */}
        <div className="pointer-events-none absolute inset-0 bg-radial-gold opacity-40" />
        <span className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />

        <div className="relative">
          <span className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
            Ваш стол
          </span>
          <div className="mx-auto my-4 flex h-20 w-20 items-center justify-center rounded-full border-2 border-gold/60 bg-night/60">
            <span className="font-playfair text-4xl text-gold-gradient">
              {match.tableId}
            </span>
          </div>
          <h3 className="font-script text-4xl text-gold-soft sm:text-5xl">
            {match.tableName}
          </h3>
          <p className="mt-1 font-cormorant text-lg italic text-ivory-soft/70">
            {match.subtitle}
          </p>

          <div className="mx-auto my-6 flex items-center justify-center gap-3 text-gold">
            <span className="hairline w-12" />
            <Heart className="h-3.5 w-3.5" />
            <span className="hairline w-12" />
          </div>

          <p className="font-cormorant text-base text-ivory-soft/80">
            Рады видеть вас,{" "}
            <span className="font-playfair text-ivory">{match.guest}</span>
          </p>

          {match.seatMates.length > 0 && (
            <div className="mt-6">
              <p className="font-playfair text-[0.66rem] uppercase tracking-luxe text-gold">
                Рядом с вами сидят
              </p>
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                {match.seatMates.map((g, i) => (
                  <span
                    key={i}
                    className="rounded-full border border-gold/25 bg-night/40 px-3 py-1 font-cormorant text-sm text-ivory-soft/85"
                  >
                    {g}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
        <span className="pointer-events-none absolute inset-x-8 bottom-0 h-px bg-gradient-to-r from-transparent via-gold/40 to-transparent" />
      </div>
    </div>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

function pluralGuests(n: number) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "гость";
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return "гостя";
  return "гостей";
}
