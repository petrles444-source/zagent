"use client"

import * as React from "react"
import {
  Sparkles,
  MousePointerClick,
  Loader,
  LayoutGrid,
  Type,
  Image as ImageIcon,
  ToggleLeft,
  TextCursorInput,
  Gauge,
  MessageSquare,
  Heart,
  History,
  Search,
  Github,
  Wand2,
  X,
  Layers,
  Copy,
  Check,
  ClipboardList,
  Sparkle,
  Star,
  Keyboard,
  Flame,
} from "lucide-react"
import { CATEGORIES, EFFECTS, type CSSEffect } from "@/data/effects"
import { EffectCard } from "@/components/effects/effect-card"
import { EffectDetailDialog } from "@/components/effects/effect-detail-dialog"
import { ShortcutHelp } from "@/components/effects/shortcut-help"
import { ThemeToggle } from "@/components/effects/theme-toggle"
import { ToastProvider, useFxToast } from "@/components/effects/toast-provider"
import { useFavorites } from "@/hooks/use-favorites"
import { useRecent } from "@/hooks/use-recent"
import { useViews } from "@/hooks/use-views"
import { cn } from "@/lib/utils"

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Sparkles,
  MousePointerClick,
  Loader,
  LayoutGrid,
  Type,
  Image: ImageIcon,
  ToggleLeft,
  TextCursorInput,
  Gauge,
  MessageSquare,
  Heart,
  History,
  Flame,
}

interface ApiResponse {
  effects: CSSEffect[]
  categories: { id: string; name: string; icon: string; count: number }[]
  total: number
  filtered: number
  favoritesCount: number
  recentCount: number
  popularCount: number
  topColors: string[]
}

export default function Home() {
  // Toast context must wrap the gallery so copy actions can surface feedback.
  return (
    <ToastProvider>
      <Gallery />
    </ToastProvider>
  )
}

function Gallery() {
  const [category, setCategory] = React.useState<string>("all")
  const [query, setQuery] = React.useState("")
  const [debounced, setDebounced] = React.useState("")
  const [effects, setEffects] = React.useState<CSSEffect[]>([])
  const [cats, setCats] = React.useState<{ id: string; name: string; icon: string; count: number }[]>([])
  const [loading, setLoading] = React.useState(true)
  const [total, setTotal] = React.useState(0)
  const [filtered, setFiltered] = React.useState(0)
  const [active, setActive] = React.useState<CSSEffect | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [helpOpen, setHelpOpen] = React.useState(false)
  const [copiedId, setCopiedId] = React.useState<string | null>(null)
  // Index of the focused card for keyboard navigation (arrow keys / Enter).
  const [focusedIndex, setFocusedIndex] = React.useState<number>(-1)
  // Color filter: when set, only effects whose CSS uses this hex are shown.
  const [colorFilter, setColorFilter] = React.useState<string>("")
  // Top accent colors across the library (populated from the API).
  const [topColors, setTopColors] = React.useState<string[]>([])

  const { favorites, toggle: toggleFav, has: hasFav, hydrated: favHydrated, count: favCount } = useFavorites()
  const { recent, push: pushRecent, hydrated: recentHydrated, count: recentCount } = useRecent()
  const { popularIds, recordView, count: popularCount, hydrated: viewsHydrated } = useViews()
  const { show: showToast } = useFxToast()

  // Debounce search
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 200)
    return () => clearTimeout(t)
  }, [query])

  // Fetch effects from the API. Include the favorites + recent lists so the
  // API can compute their counts and filter those virtual views server-side.
  React.useEffect(() => {
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams()
    if (category) params.set("category", category)
    if (debounced) params.set("q", debounced)
    if (colorFilter) params.set("color", colorFilter)
    if (favHydrated) params.set("favorites", Array.from(favorites).join(","))
    if (recentHydrated) params.set("recent", recent.join(","))
    if (viewsHydrated) params.set("popular", popularIds.join(","))
    fetch(`/api/effects?${params.toString()}`)
      .then((r) => r.json())
      .then((data: ApiResponse) => {
        if (cancelled) return
        setEffects(data.effects)
        setCats(data.categories)
        setTotal(data.total)
        setFiltered(data.filtered)
        if (data.topColors?.length) setTopColors(data.topColors)
      })
      .catch(() => {
        if (cancelled) return
        setEffects([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [category, debounced, colorFilter, favHydrated, favorites, recentHydrated, recent, viewsHydrated, popularIds])

  const handleOpen = (effect: CSSEffect) => {
    setActive(effect)
    setDialogOpen(true)
    pushRecent(effect.id)
    recordView(effect.id)
  }

  // Navigate to a sibling effect from within the detail dialog (prev/next).
  const handleNavigate = (effect: CSSEffect) => {
    setActive(effect)
    pushRecent(effect.id)
    recordView(effect.id)
  }

  // Export the current view (favorites, recent, or popular) as a copyable list.
  const handleExport = async () => {
    const ids =
      category === "favorites"
        ? Array.from(favorites)
        : category === "recent"
          ? recent
          : popularIds
    const byId = new Map(EFFECTS.map((e) => [e.id, e]))
    const items = ids
      .map((id) => byId.get(id))
      .filter((e): e is CSSEffect => Boolean(e))
    if (items.length === 0) {
      showToast("Nothing to export yet", "error")
      return
    }
    const lines = items.map((e) => `- ${e.name} (${e.category}) — ${e.id}`)
    const text = `CSSFX ${category} (${items.length})\n${lines.join("\n")}\n`
    try {
      await navigator.clipboard.writeText(text)
      showToast(`Copied ${items.length} ${category} as a list`, "success")
    } catch {
      showToast("Couldn't copy — try again", "error")
    }
  }

  // First-visit onboarding hint (dismissed state persisted to localStorage).
  const [showHint, setShowHint] = React.useState(false)
  React.useEffect(() => {
    try {
      const seen = window.localStorage.getItem("cssfx:hint-seen")
      if (!seen) setShowHint(true)
    } catch {
      // ignore
    }
  }, [])
  const dismissHint = () => {
    setShowHint(false)
    try {
      window.localStorage.setItem("cssfx:hint-seen", "1")
    } catch {
      // ignore
    }
  }

  // Deep-link: open a specific effect from the ?effect=ID query param on mount.
  // Also restores playground state (accent/scale/backdrop/show) if present.
  // The params are consumed once and then cleaned from the address bar.
  const [initialPlayground, setInitialPlayground] = React.useState<
    Partial<{ accent: string; scale: number; backdrop: string; show: boolean }>
  >({})

  React.useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams(window.location.search)
    const id = params.get("effect")
    if (!id) return
    const found = EFFECTS.find((e) => e.id === id)
    if (found) {
      // Restore playground state from the URL if provided.
      const pg: Partial<{ accent: string; scale: number; backdrop: string; show: boolean }> = {}
      const ac = params.get("accent")
      const sc = params.get("scale")
      const bd = params.get("backdrop")
      const sh = params.get("show")
      if (ac) pg.accent = ac
      if (sc) pg.scale = parseFloat(sc) || 1
      if (bd) pg.backdrop = bd
      if (sh === "1") pg.show = true
      if (Object.keys(pg).length > 0) setInitialPlayground(pg)
      handleOpen(found)
      // Clean the URL so a refresh doesn't reopen the dialog.
      const url = new URL(window.location.href)
      url.searchParams.delete("effect")
      url.searchParams.delete("accent")
      url.searchParams.delete("scale")
      url.searchParams.delete("backdrop")
      url.searchParams.delete("show")
      window.history.replaceState({}, "", url.toString())
    }
  }, [])

  // Copy a shareable deep-link for an effect (with playground state) to clipboard.
  const handleShare = async (
    effect: CSSEffect,
    state?: { accent?: string; scale?: number; backdrop?: string; show?: boolean }
  ) => {
    try {
      const url = new URL(window.location.href)
      url.searchParams.set("effect", effect.id)
      if (state?.accent) url.searchParams.set("accent", state.accent)
      if (state?.scale && state.scale !== 1) url.searchParams.set("scale", state.scale.toString())
      if (state?.backdrop && state.backdrop !== "auto")
        url.searchParams.set("backdrop", state.backdrop)
      if (state?.show) url.searchParams.set("show", "1")
      const link = url.toString()
      await navigator.clipboard.writeText(link)
      showToast(`Copied link to "${effect.name}"`, "success")
    } catch {
      showToast("Couldn't copy link — try again", "error")
    }
  }

  const handleQuickCopy = async (effect: CSSEffect) => {
    try {
      await navigator.clipboard.writeText(effect.css)
      setCopiedId(effect.id)
      setTimeout(() => setCopiedId(null), 1500)
      showToast(`Copied "${effect.name}" CSS`, "success")
    } catch {
      showToast("Couldn't copy — try again", "error")
    }
  }

  // Global keyboard navigation when no input is focused.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // "?" opens the shortcut cheatsheet from anywhere (even in inputs).
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        // Avoid interfering with actual typing of "?" — only trigger when not
        // in an input, OR when Shift+/ produces "?" outside inputs.
        const target = e.target as HTMLElement | null
        const tag = target?.tagName
        if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return
        e.preventDefault()
        setHelpOpen((v) => !v)
        return
      }
      // Don't hijack typing in the search box.
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return
      // Skip card navigation when a dialog or the help modal is open.
      if (dialogOpen || helpOpen) return

      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault()
        setFocusedIndex((i) => {
          const next = i < 0 ? 0 : Math.min(i + 1, effects.length - 1)
          return next
        })
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault()
        setFocusedIndex((i) => Math.max(0, i - 1))
      } else if (e.key === "Enter" && focusedIndex >= 0 && focusedIndex < effects.length) {
        e.preventDefault()
        handleOpen(effects[focusedIndex])
      } else if (e.key === "/" && !query) {
        // "/" focuses the search box for power users.
        e.preventDefault()
        document.querySelector<HTMLInputElement>('input[placeholder^="Search"]')?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [effects, focusedIndex, query, dialogOpen, helpOpen])

  // Move DOM focus to the focused card so screen readers & scroll follow.
  React.useEffect(() => {
    if (focusedIndex < 0 || loading) return
    const el = document.querySelector<HTMLElement>(
      `[data-card-index="${focusedIndex}"]`
    )
    el?.focus()
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [focusedIndex, loading])

  const scrollToGallery = () => {
    document
      .getElementById("gallery")
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {/* ===== Header ===== */}
      <header className="sticky top-0 z-40 w-full border-b border-border/70 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <button
            type="button"
            onClick={() => {
              setCategory("all")
              setQuery("")
              window.scrollTo({ top: 0, behavior: "smooth" })
            }}
            className="flex items-center gap-2 transition hover:opacity-80"
            aria-label="CSSFX home"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-400 via-teal-400 to-cyan-400 text-white shadow-md shadow-emerald-500/20">
              <Wand2 className="h-5 w-5" />
            </div>
            <div className="hidden text-left sm:block">
              <p className="text-base font-bold leading-none tracking-tight">
                CSSFX
              </p>
              <p className="text-[10px] text-muted-foreground">
                Effect Library
              </p>
            </div>
          </button>

          {/* Search */}
          <div className="relative ml-auto w-full max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search effects, tags…"
              className="h-10 w-full rounded-lg border border-border bg-muted/40 pl-9 pr-9 text-sm outline-none transition focus:border-primary/50 focus:bg-background focus:ring-2 focus:ring-primary/20"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Popular quick button */}
          <button
            type="button"
            onClick={() => {
              setCategory("popular")
              scrollToGallery()
            }}
            className={cn(
              "relative hidden h-9 w-9 items-center justify-center rounded-lg border transition sm:inline-flex",
              category === "popular"
                ? "border-orange-500/50 bg-orange-500/15 text-orange-500"
                : "border-border bg-background text-foreground/70 hover:bg-muted hover:text-orange-500"
            )}
            aria-label={`Show popular effects (${popularCount})`}
            title={`Popular (${popularCount})`}
          >
            <Flame className={cn("h-4 w-4", popularCount > 0 && "text-orange-500")} />
            {popularCount > 0 && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-orange-500 px-1 text-[10px] font-bold text-white">
                {popularCount}
              </span>
            )}
          </button>

          {/* Recent quick button */}
          <button
            type="button"
            onClick={() => {
              setCategory("recent")
              scrollToGallery()
            }}
            className={cn(
              "relative hidden h-9 w-9 items-center justify-center rounded-lg border transition sm:inline-flex",
              category === "recent"
                ? "border-primary/50 bg-primary/15 text-primary"
                : "border-border bg-background text-foreground/70 hover:bg-muted hover:text-primary"
            )}
            aria-label={`Show recently viewed (${recentCount})`}
            title={`Recent (${recentCount})`}
          >
            <History className={cn("h-4 w-4", recentCount > 0 && "text-primary")} />
            {recentCount > 0 && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
                {recentCount}
              </span>
            )}
          </button>

          {/* Favorites quick button */}
          <button
            type="button"
            onClick={() => {
              setCategory("favorites")
              scrollToGallery()
            }}
            className={cn(
              "relative inline-flex h-9 w-9 items-center justify-center rounded-lg border transition",
              category === "favorites"
                ? "border-amber-400/50 bg-amber-400/15 text-amber-500"
                : "border-border bg-background text-foreground/70 hover:bg-muted hover:text-amber-500"
            )}
            aria-label={`Show favorites (${favCount})`}
            title={`Favorites (${favCount})`}
          >
            <Heart className={cn("h-4 w-4", favCount > 0 && "fill-amber-400 text-amber-500")} />
            {favCount > 0 && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-bold text-white">
                {favCount}
              </span>
            )}
          </button>

          <a
            href="https://developer.mozilla.org/en-US/docs/Web/CSS"
            target="_blank"
            rel="noreferrer"
            className="hidden h-9 w-9 items-center justify-center rounded-lg border border-border bg-background text-foreground transition hover:bg-muted sm:inline-flex"
            aria-label="MDN CSS docs"
          >
            <Github className="h-4 w-4" />
          </a>
          <button
            type="button"
            onClick={() => setHelpOpen(true)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-background text-foreground/70 transition hover:bg-muted hover:text-foreground"
            aria-label="Keyboard shortcuts (press ?)"
            title="Keyboard shortcuts (?)"
          >
            <Keyboard className="h-4 w-4" />
          </button>
          <ThemeToggle />
        </div>
      </header>

      {/* ===== Hero ===== */}
      <section className="relative overflow-hidden border-b border-border/70">
        <div className="pointer-events-none absolute inset-0 opacity-60">
          <div className="fx-float-a absolute -left-24 -top-24 h-72 w-72 rounded-full bg-emerald-500/20 blur-3xl" />
          <div className="fx-float-b absolute right-0 top-0 h-72 w-72 rounded-full bg-fuchsia-500/20 blur-3xl" />
          <div className="fx-float-a absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl" />
        </div>
        <div className="relative mx-auto max-w-7xl px-4 py-14 sm:px-6 sm:py-20">
          <div className="mx-auto max-w-3xl text-center">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs font-medium text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-emerald-500" />
              {total} handcrafted effects · 9 categories · copy &amp; paste ready
            </span>
            <h1 className="mt-5 text-4xl font-extrabold tracking-tight sm:text-6xl">
              A beautiful{" "}
              <span className="fx-hue bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 bg-clip-text text-transparent">
                CSS effect
              </span>{" "}
              library
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-base text-muted-foreground sm:text-lg">
              Browse live, interactive demos of buttons, loaders, cards, text,
              backgrounds, toggles, inputs, progress bars and tooltips. Every
              effect ships with clean HTML &amp; CSS you can copy in one click.
            </p>

            {/* Stat chips */}
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              {CATEGORIES.filter((c) => c.id !== "all").map((c) => {
                const Icon = ICONS[c.icon] ?? Sparkles
                const count = cats.find((x) => x.id === c.id)?.count
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => {
                      setCategory(c.id)
                      scrollToGallery()
                    }}
                    className="group inline-flex items-center gap-2 rounded-xl border border-border bg-card px-3.5 py-2 text-sm font-medium shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    {c.name}
                    <span className="rounded-full bg-muted px-1.5 text-[11px] text-muted-foreground">
                      {count ?? ""}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ===== Gallery ===== */}
      <main id="gallery" className="mx-auto w-full max-w-7xl flex-1 px-4 py-10 sm:px-6">
        {/* Category tabs */}
        <div className="mb-6 flex items-center gap-2 overflow-x-auto scroll-thin pb-2">
          {cats.map((c) => {
            const Icon = ICONS[c.icon] ?? Sparkles
            const isActive = category === c.id
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setCategory(c.id)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition",
                  isActive
                    ? "border-primary bg-primary text-primary-foreground shadow-sm"
                    : c.id === "favorites"
                      ? "border-border bg-background text-foreground/80 hover:border-amber-400/50 hover:text-amber-500"
                      : c.id === "recent"
                        ? "border-border bg-background text-foreground/80 hover:border-primary/40 hover:text-primary"
                        : c.id === "popular"
                          ? "border-border bg-background text-foreground/80 hover:border-orange-500/50 hover:text-orange-500"
                          : "border-border bg-background text-foreground/80 hover:bg-muted"
                )}
              >
                <Icon className={cn("h-4 w-4", c.id === "favorites" && c.count > 0 && "fill-current", c.id === "recent" && c.count > 0 && "text-primary", c.id === "popular" && c.count > 0 && "text-orange-500")} />
                {c.name}
                <span
                  className={cn(
                    "rounded-full px-1.5 text-[11px]",
                    isActive
                      ? "bg-primary-foreground/20"
                      : "bg-muted text-muted-foreground"
                  )}
                >
                  {c.count}
                </span>
              </button>
            )
          })}
        </div>

        {/* Color filter row — pick a hex to find effects that use it */}
        {topColors.length > 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Color
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              {topColors.map((hex) => {
                const active = colorFilter === hex
                return (
                  <button
                    key={hex}
                    type="button"
                    onClick={() => setColorFilter(active ? "" : hex)}
                    aria-label={`Filter by color ${hex}`}
                    aria-pressed={active}
                    title={hex}
                    className={cn(
                      "h-6 w-6 rounded-full border-2 transition",
                      active
                        ? "border-foreground ring-2 ring-ring ring-offset-1 ring-offset-background"
                        : "border-border/60 hover:scale-110 hover:border-foreground/50"
                    )}
                    style={{ backgroundColor: hex }}
                  />
                )
              })}
              {colorFilter && (
                <button
                  type="button"
                  onClick={() => setColorFilter("")}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                  Clear color
                </button>
              )}
            </div>
          </div>
        )}

        {/* Results bar + keyboard hint */}
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {loading ? (
              "Loading…"
            ) : (
              <>
                Showing{" "}
                <span className="font-semibold text-foreground">{filtered}</span>{" "}
                of {total} effects
                {category !== "all" && (
                  <>
                    {" "}
                    in{" "}
                    <span className="font-semibold text-foreground capitalize">
                      {category}
                    </span>
                  </>
                )}
                {debounced && (
                  <>
                    {" "}
                    for &ldquo;
                    <span className="font-semibold text-foreground">{debounced}</span>
                    &rdquo;
                  </>
                )}
              </>
            )}
          </p>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 text-[11px] text-muted-foreground/70 sm:inline-flex">
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">/</kbd>
              search{" · "}
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">←→</kbd>
              navigate{" · "}
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">Enter</kbd>
              open
            </span>
            {(category === "favorites" || category === "recent" || category === "popular") && effects.length > 0 && (
              <button
                type="button"
                onClick={handleExport}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
                title={`Copy ${category} as a text list`}
              >
                <ClipboardList className="h-3 w-3" />
                Export
              </button>
            )}
            {(category !== "all" || debounced || colorFilter) && (
              <button
                type="button"
                onClick={() => {
                  setCategory("all")
                  setQuery("")
                  setColorFilter("")
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
              >
                <X className="h-3 w-3" />
                Reset
              </button>
            )}
          </div>
        </div>

        {/* First-visit onboarding hint */}
        {showHint && (
          <div className="fx-fade-up mb-5 flex items-start gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Sparkle className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-semibold text-foreground">Welcome to CSSFX 👋</p>
              <p className="mt-0.5 text-muted-foreground">
                Tap{" "}
                <Star className="inline h-3.5 w-3.5 fill-amber-400 text-amber-500 align-text-bottom" />
                to favorite effects, open any card to tweak it in the{" "}
                <span className="font-medium text-foreground">Playground</span>, and press{" "}
                <kbd className="rounded border border-border bg-background px-1 py-0.5 font-mono text-[10px]">/</kbd>{" "}
                to search. Your favorites &amp; recent views are saved on this device.
              </p>
            </div>
            <button
              type="button"
              onClick={dismissHint}
              className="shrink-0 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              Got it
            </button>
            <button
              type="button"
              onClick={dismissHint}
              aria-label="Dismiss hint"
              className="shrink-0 rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Grid */}
        {loading ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="overflow-hidden rounded-xl border border-border bg-card"
              >
                <div className="h-44 w-full animate-pulse bg-muted" />
                <div className="space-y-2 p-4">
                  <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
                  <div className="h-3 w-full animate-pulse rounded bg-muted" />
                  <div className="h-3 w-1/2 animate-pulse rounded bg-muted" />
                </div>
              </div>
            ))}
          </div>
        ) : effects.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
              {category === "favorites" ? (
                <Heart className="h-6 w-6 text-muted-foreground" />
              ) : category === "recent" ? (
                <History className="h-6 w-6 text-muted-foreground" />
              ) : category === "popular" ? (
                <Flame className="h-6 w-6 text-muted-foreground" />
              ) : (
                <Search className="h-6 w-6 text-muted-foreground" />
              )}
            </div>
            <h3 className="mt-4 text-lg font-semibold">
              {category === "favorites"
                ? "No favorites yet"
                : category === "recent"
                  ? "No recently viewed effects"
                  : category === "popular"
                    ? "No popular effects yet"
                    : "No effects found"}
            </h3>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              {category === "favorites"
                ? "Tap the star on any effect to save it here for quick access."
                : category === "recent"
                  ? "Effects you open will show up here so you can jump back to them."
                  : category === "popular"
                    ? "Effects you open most often will surface here, ranked by views."
                    : "Try a different keyword or clear your filters to see the full library."}
            </p>
            <button
              type="button"
              onClick={() => {
                setCategory("all")
                setQuery("")
              }}
              className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
            >
              <Layers className="h-4 w-4" />
              Browse all effects
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {effects.map((effect, i) => (
              <div
                key={effect.id}
                className={cn(
                  "group/card relative outline-none transition",
                  focusedIndex === i && "ring-2 ring-ring ring-offset-2 ring-offset-background rounded-xl"
                )}
                data-card-index={i}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    handleOpen(effect)
                  }
                }}
              >
                <EffectCard
                  effect={effect}
                  index={i}
                  onOpen={handleOpen}
                  isFavorite={hasFav(effect.id)}
                  onToggleFavorite={toggleFav}
                />
                <button
                  type="button"
                  onClick={() => handleQuickCopy(effect)}
                  title="Copy CSS"
                  className="absolute bottom-[88px] right-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background/90 text-foreground/70 opacity-0 shadow-sm backdrop-blur transition hover:text-foreground group-hover/card:opacity-100"
                >
                  {copiedId === effect.id ? (
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* ===== Footer (sticky to bottom) ===== */}
      <footer className="mt-auto border-t border-border bg-background">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-emerald-400 to-cyan-400 text-white">
              <Wand2 className="h-3.5 w-3.5" />
            </div>
            <span>
              <span className="font-semibold text-foreground">CSSFX</span> ·
              Built with pure CSS. Copy, paste, ship.
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span>{total} effects</span>
            <span className="hidden sm:inline">·</span>
            <span className="hidden sm:inline">9 categories</span>
            {recentCount > 0 && (
              <>
                <span className="hidden sm:inline">·</span>
                <span className="inline-flex items-center gap-1">
                  <History className="h-3 w-3 text-primary" />
                  {recentCount} recent
                </span>
              </>
            )}
            {favCount > 0 && (
              <>
                <span className="hidden sm:inline">·</span>
                <span className="inline-flex items-center gap-1">
                  <Heart className="h-3 w-3 fill-amber-400 text-amber-500" />
                  {favCount} saved
                </span>
              </>
            )}
            <span className="hidden sm:inline">·</span>
            <a
              href="https://developer.mozilla.org/en-US/docs/Web/CSS"
              target="_blank"
              rel="noreferrer"
              className="transition hover:text-foreground"
            >
              MDN Docs ↗
            </a>
          </div>
        </div>
      </footer>

      {/* ===== Detail dialog ===== */}
      <EffectDetailDialog
        effect={active}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        isFavorite={active ? hasFav(active.id) : false}
        onToggleFavorite={toggleFav}
        onCopy={(msg, variant) => showToast(msg, variant)}
        onShare={handleShare}
        siblings={effects}
        onNavigate={handleNavigate}
        initialPlayground={initialPlayground}
      />

      {/* ===== Keyboard shortcut help ===== */}
      <ShortcutHelp open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}
