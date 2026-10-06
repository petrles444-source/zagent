"use client"

import * as React from "react"
import {
  Atom,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Link2,
  MonitorSmartphone,
  Moon,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  Tag,
} from "lucide-react"
import { EFFECTS, type CSSEffect } from "@/data/effects"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { EffectPreview, type PreviewBackdrop } from "./effect-preview"
import { CodeBlock } from "./code-block"
import { PlaygroundPanel } from "./playground-panel"
import { useCodeTheme } from "@/hooks/use-code-theme"
import { toComponent, componentFilename, type Framework } from "@/lib/framework-transforms"
import { cn } from "@/lib/utils"

// Neutral/greyscale hexes we don't treat as a "color" for related-by-color.
const NEUTRAL = new Set([
  "#fff", "#ffffff", "#000", "#000000", "#111", "#222", "#333", "#444",
  "#555", "#666", "#777", "#888", "#999", "#aaa", "#bbb", "#ccc", "#ddd", "#eee",
  "#f1f5f9", "#e5e7eb", "#d1d5db", "#cbd5e1", "#94a3b8", "#64748b",
  "#475569", "#334155", "#1e293b", "#0f172a", "#0b1020", "#020617",
  "#1f2937", "#111827", "#374151", "#4b5563", "#6b7280", "#9ca3af",
  "#f8fafc", "#f9fafb", "#f3f4f6", "#e0e5ec", "#b8bcc2",
])

/** Extract non-neutral 6-digit hex colors from a CSS source (lowercased). */
function extractColors(css: string): Set<string> {
  const out = new Set<string>()
  const re = /#([0-9a-fA-F]{6})\b/g
  let m: RegExpExecArray | null
  while ((m = re.exec(css)) !== null) {
    const hex = m[0].toLowerCase()
    if (!NEUTRAL.has(hex)) out.add(hex)
  }
  return out
}

/** Serializable playground state for deep-linking. */
export interface PlaygroundState {
  accent: string
  scale: number
  backdrop: PreviewBackdrop
  show: boolean
}

interface EffectDetailDialogProps {
  effect: CSSEffect | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isFavorite?: boolean
  onToggleFavorite?: (id: string) => void
  /** Called with a message + variant whenever a copy action completes. */
  onCopy?: (message: string, variant?: "success" | "error") => void
  /** Full list of effects currently in the gallery (for prev/next). */
  siblings?: CSSEffect[]
  /** Navigate to a sibling effect by id (used by prev/next). */
  onNavigate?: (effect: CSSEffect) => void
  /** Copy a shareable deep-link, optionally including playground state. */
  onShare?: (effect: CSSEffect, state?: PlaygroundState) => void
  /** Initial playground state (restored from a deep-link). */
  initialPlayground?: Partial<PlaygroundState>
}

export function EffectDetailDialog({
  effect,
  open,
  onOpenChange,
  isFavorite = false,
  onToggleFavorite,
  onCopy,
  siblings,
  onNavigate,
  onShare,
  initialPlayground,
}: EffectDetailDialogProps) {
  const [copiedAll, setCopiedAll] = React.useState(false)
  const { theme: codeTheme, pref: codePref, toggle: toggleCodeTheme } = useCodeTheme()

  // Playground state — resets whenever the effect changes. Initialized from
  // `initialPlayground` (deep-link) on first mount only.
  const [scale, setScale] = React.useState(initialPlayground?.scale ?? 1)
  const [accent, setAccent] = React.useState(initialPlayground?.accent ?? "")
  const [backdrop, setBackdrop] = React.useState<PreviewBackdrop>(initialPlayground?.backdrop ?? "auto")
  const [showPlayground, setShowPlayground] = React.useState(initialPlayground?.show ?? false)

  // Reset playground when switching effects (but not on the initial mount
  // when restoring from a deep-link).
  const isFirstMount = React.useRef(true)
  React.useEffect(() => {
    if (isFirstMount.current) {
      isFirstMount.current = false
      return
    }
    setScale(1)
    setAccent("")
    setBackdrop("auto")
    setShowPlayground(false)
  }, [effect?.id])

  const resetPlayground = () => {
    setScale(1)
    setAccent("")
    setBackdrop("auto")
  }

  // Apply initialPlayground (from a deep-link) when it arrives — useState
  // initializers only run once, so we sync via effect for the deep-link case.
  React.useEffect(() => {
    if (!initialPlayground) return
    if (initialPlayground.scale !== undefined) setScale(initialPlayground.scale)
    if (initialPlayground.accent !== undefined) setAccent(initialPlayground.accent)
    if (initialPlayground.backdrop !== undefined) setBackdrop(initialPlayground.backdrop)
    if (initialPlayground.show !== undefined) setShowPlayground(initialPlayground.show)
  }, [initialPlayground])

  // Active framework tab for the code export panel.
  const [fwTab, setFwTab] = React.useState<Framework>("react")
  // Reset to React when switching effects (simpler mental model).
  React.useEffect(() => {
    setFwTab("react")
  }, [effect?.id])

  // Build a ready-to-paste component for the active framework. Memoized before
  // the early return so hook order stays stable.
  const componentCode = React.useMemo(
    () => (effect ? toComponent(effect, fwTab) : ""),
    [effect, fwTab]
  )
  const [copiedComponent, setCopiedComponent] = React.useState(false)

  // Compute up to 6 "related" effects: same category, shared tags, and shared
  // CSS colors. Excludes the current effect. Memoized before the early return.
  const relatedEffects = React.useMemo(() => {
    if (!effect) return [] as CSSEffect[]
    const tagSet = new Set(effect.tags)
    const myColors = extractColors(effect.css)
    const scored = EFFECTS.filter((e) => e.id !== effect.id).map((e) => {
      let score = 0
      if (e.category === effect.category) score += 3
      for (const t of e.tags) if (tagSet.has(t)) score += 1
      // Shared accent colors (non-neutral hexes) indicate a similar palette.
      if (myColors.size > 0) {
        const theirColors = extractColors(e.css)
        let shared = 0
        for (const c of theirColors) if (myColors.has(c)) shared++
        score += Math.min(shared, 3)
      }
      return { e, score }
    })
    return scored
      .filter((s) => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 6)
      .map((s) => s.e)
  }, [effect])

  // Prev/next navigation + arrow-key support.
  const currentIndex = effect && siblings ? siblings.findIndex((e) => e.id === effect.id) : -1
  const hasPrev = currentIndex > 0
  const hasNext = siblings && currentIndex >= 0 && currentIndex < siblings.length - 1

  const goPrev = React.useCallback(() => {
    if (hasPrev && siblings && onNavigate) onNavigate(siblings[currentIndex - 1])
  }, [hasPrev, siblings, currentIndex, onNavigate])
  const goNext = React.useCallback(() => {
    if (hasNext && siblings && onNavigate) onNavigate(siblings[currentIndex + 1])
  }, [hasNext, siblings, currentIndex, onNavigate])

  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft" && hasPrev) {
        e.preventDefault()
        goPrev()
      } else if (e.key === "ArrowRight" && hasNext) {
        e.preventDefault()
        goNext()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, hasPrev, hasNext, goPrev, goNext])

  if (!effect) return null

  const combinedSnippet = `<!-- ${effect.name} -->\n<style>\n${effect.css}\n</style>\n\n${effect.html}\n`

  const handleDownload = () => {
    const full = `<!-- ${effect.name} - HTML -->\n${effect.html}\n\n/* ${effect.name} - CSS */\n${effect.css}\n`
    const blob = new Blob([full], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${effect.id}.css`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopyAll = async () => {
    try {
      await navigator.clipboard.writeText(combinedSnippet)
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 1800)
      onCopy?.(`Copied "${effect.name}" snippet`, "success")
    } catch {
      onCopy?.("Couldn't copy — try again", "error")
    }
  }

  const handleCopyComponent = async () => {
    try {
      await navigator.clipboard.writeText(componentCode)
      setCopiedComponent(true)
      setTimeout(() => setCopiedComponent(false), 1800)
      onCopy?.(`Copied "${effect.name}" as ${fwTab}`, "success")
    } catch {
      onCopy?.("Couldn't copy — try again", "error")
    }
  }

  // Download the generated component as a file with the right extension.
  const handleDownloadComponent = () => {
    const blob = new Blob([componentCode], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = componentFilename(effect, fwTab)
    a.click()
    URL.revokeObjectURL(url)
    onCopy?.(`Downloaded ${componentFilename(effect, fwTab)}`, "success")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="border-b border-border px-6 py-4">
          <div className="flex items-start justify-between gap-3 pr-8">
            <div className="min-w-0 space-y-1">
              <DialogTitle className="text-xl">{effect.name}</DialogTitle>
              <DialogDescription>{effect.description}</DialogDescription>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {/* Prev/next */}
              {siblings && siblings.length > 1 && (
                <div className="flex items-center gap-0.5 rounded-md border border-border bg-background p-0.5">
                  <button
                    type="button"
                    onClick={goPrev}
                    disabled={!hasPrev}
                    aria-label="Previous effect"
                    className="inline-flex h-7 w-7 items-center justify-center rounded text-foreground/70 transition hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="px-1 text-[11px] tabular-nums text-muted-foreground">
                    {currentIndex >= 0 ? currentIndex + 1 : "–"}/{siblings.length}
                  </span>
                  <button
                    type="button"
                    onClick={goNext}
                    disabled={!hasNext}
                    aria-label="Next effect"
                    className="inline-flex h-7 w-7 items-center justify-center rounded text-foreground/70 transition hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              )}
              {onToggleFavorite && (
                <button
                  type="button"
                  onClick={() => onToggleFavorite(effect.id)}
                  aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
                  aria-pressed={isFavorite}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition",
                    isFavorite
                      ? "border-amber-400/50 bg-amber-400/15 text-amber-500 hover:bg-amber-400/25"
                      : "border-border bg-background text-foreground hover:bg-muted"
                  )}
                >
                  <Star className={cn("h-3.5 w-3.5", isFavorite && "fill-amber-400")} />
                  <span className="hidden sm:inline">{isFavorite ? "Favorited" : "Favorite"}</span>
                </button>
              )}
              <button
                type="button"
                onClick={handleDownload}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
              >
                <Download className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Download</span>
              </button>
              {onShare && (
                <button
                  type="button"
                  onClick={() =>
                    onShare(effect, { accent, scale, backdrop, show: showPlayground })
                  }
                  aria-label="Copy shareable link"
                  title="Copy shareable link (includes playground state)"
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
                >
                  <Link2 className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Share</span>
                </button>
              )}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium capitalize text-primary">
              {effect.category}
            </span>
            {effect.tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
              >
                <Tag className="h-2.5 w-2.5" />
                {tag}
              </span>
            ))}
          </div>
        </DialogHeader>

        <div className="grid max-h-[70vh] grid-cols-1 gap-0 md:grid-cols-2">
          {/* Live preview + playground */}
          <div className="flex flex-col border-b border-border md:border-b-0 md:border-r">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Live Preview
              </span>
              <button
                type="button"
                onClick={() => setShowPlayground((v) => !v)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium transition",
                  showPlayground
                    ? "border-primary/50 bg-primary/10 text-primary"
                    : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
                aria-pressed={showPlayground}
              >
                <SlidersHorizontal className="h-3 w-3" />
                Playground
              </button>
            </div>
            {showPlayground && (
              <PlaygroundPanel
                scale={scale}
                onScaleChange={setScale}
                accent={accent}
                onAccentChange={setAccent}
                backdrop={backdrop}
                onBackdropChange={setBackdrop}
                onReset={resetPlayground}
              />
            )}
            <div className="flex-1 overflow-auto scroll-thin">
              <EffectPreview
                effect={effect}
                className="min-h-[280px] w-full"
                backdrop={backdrop}
                scale={scale}
                accent={accent}
              />
            </div>
          </div>

          {/* Code */}
          <div className="flex flex-col">
            <Tabs defaultValue="css" className="flex flex-1 flex-col">
              <div className="flex items-center justify-between border-b border-border px-3 pt-3">
                <TabsList className="bg-muted/60">
                  <TabsTrigger value="css" className="text-xs">CSS</TabsTrigger>
                  <TabsTrigger value="html" className="text-xs">HTML</TabsTrigger>
                  <TabsTrigger value="react" className="text-xs gap-1.5">
                    <Atom className="h-3 w-3" />
                    React
                  </TabsTrigger>
                </TabsList>
                <div className="mb-2 flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={toggleCodeTheme}
                    title={
                      codePref === "auto"
                        ? `Code theme: auto (follows page — ${codeTheme})`
                        : `Code theme: ${codeTheme}`
                    }
                    aria-label={`Switch code theme (currently ${codePref === "auto" ? "auto" : codeTheme})`}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background text-foreground/70 transition hover:bg-muted hover:text-foreground"
                  >
                    {codePref === "auto" ? (
                      <MonitorSmartphone className="h-3.5 w-3.5" />
                    ) : codeTheme === "dark" ? (
                      <Moon className="h-3.5 w-3.5" />
                    ) : (
                      <Sun className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={handleCopyAll}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground/80 transition hover:bg-muted hover:text-foreground"
                    title="Copy full HTML + CSS snippet"
                  >
                    {copiedAll ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-500" />
                        Copied!
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        Copy snippet
                      </>
                    )}
                  </button>
                </div>
              </div>
              <TabsContent
                value="css"
                className="mt-0 flex-1 overflow-auto scroll-thin p-3"
              >
                <CodeBlock code={effect.css} language="css" theme={codeTheme} />
              </TabsContent>
              <TabsContent
                value="html"
                className="mt-0 flex-1 overflow-auto scroll-thin p-3"
              >
                <CodeBlock code={effect.html} language="html" theme={codeTheme} />
              </TabsContent>
              <TabsContent
                value="react"
                className="mt-0 flex-1 overflow-auto scroll-thin p-3"
              >
                {/* Framework sub-selector */}
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-0.5 rounded-md bg-muted/60 p-0.5">
                    {(["react", "vue", "svelte"] as Framework[]).map((fw) => (
                      <button
                        key={fw}
                        type="button"
                        onClick={() => setFwTab(fw)}
                        className={cn(
                          "rounded px-2 py-1 text-[11px] font-medium capitalize transition",
                          fwTab === fw
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        )}
                      >
                        {fw}
                      </button>
                    ))}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={handleCopyComponent}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground/80 transition hover:bg-muted hover:text-foreground"
                      title={`Copy as a ${fwTab} component`}
                    >
                      {copiedComponent ? (
                        <>
                          <Check className="h-3 w-3 text-emerald-500" />
                          Copied!
                        </>
                      ) : (
                        <>
                          <Atom className="h-3 w-3" />
                          Copy as {fwTab === "react" ? "React" : fwTab === "vue" ? "Vue" : "Svelte"}
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={handleDownloadComponent}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background text-foreground/70 transition hover:bg-muted hover:text-foreground"
                      title={`Download ${componentFilename(effect, fwTab)}`}
                      aria-label={`Download ${fwTab} component file`}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <p className="mb-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-[11px] text-muted-foreground">
                  Self-contained {fwTab} component — CSS is scoped via a wrapper class &amp; a {fwTab === "react" ? "<style>" : "<style scoped>"} tag.
                </p>
                <CodeBlock
                  code={componentCode}
                  language={fwTab === "react" ? "jsx" : "html"}
                  theme={codeTheme}
                />
              </TabsContent>
            </Tabs>
          </div>
        </div>

        {/* Related effects */}
        {relatedEffects.length > 0 && onNavigate && (
          <div className="border-t border-border bg-muted/20 px-6 py-4">
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <Sparkles className="h-3 w-3" />
              Related effects
            </h4>
            <div className="flex flex-wrap gap-2">
              {relatedEffects.map((rel) => (
                <button
                  key={rel.id}
                  type="button"
                  onClick={() => onNavigate(rel)}
                  className="group inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground/80 transition hover:border-primary/40 hover:text-primary hover:shadow-sm"
                >
                  <span className="h-2 w-2 rounded-full bg-primary/40 transition group-hover:bg-primary" />
                  {rel.name}
                  <span className="text-[10px] capitalize text-muted-foreground">
                    {rel.category}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Footer hint */}
        {siblings && siblings.length > 1 && (
          <div className="border-t border-border bg-muted/30 px-6 py-2 text-center text-[11px] text-muted-foreground">
            Use{" "}
            <kbd className="rounded border border-border bg-background px-1 py-0.5 font-mono text-[10px]">←</kbd>{" "}
            <kbd className="rounded border border-border bg-background px-1 py-0.5 font-mono text-[10px]">→</kbd>{" "}
            to browse effects
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
