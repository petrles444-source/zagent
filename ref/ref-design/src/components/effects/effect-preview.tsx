"use client"

import * as React from "react"
import type { CSSEffect } from "@/data/effects"

const bgClasses: Record<string, string> = {
  light: "bg-white",
  dark: "bg-[#0b1020]",
  gradient:
    "bg-[linear-gradient(135deg,#f0abfc,#a78bfa,#67e8f9,#fde68a)]",
  checker:
    "bg-[conic-gradient(#e2e8f0_90deg,#f8fafc_90deg_180deg,#e2e8f0_180deg_270deg,#f8fafc_270deg)] bg-[length:20px_20px]",
}

export type PreviewBackdrop = "auto" | "light" | "dark" | "gradient" | "checker"

interface EffectPreviewProps {
  effect: CSSEffect
  className?: string
  /** When true, preview is interactive (e.g. for toggles) */
  interactive?: boolean
  /** Override the effect's default preview backdrop. */
  backdrop?: PreviewBackdrop
  /** Uniform scale factor applied to the rendered effect (playground). */
  scale?: number
  /** Accent color override — recolors the effect's dominant hue (playground). */
  accent?: string
}

// Neutral / greyscale hexes we never want to treat as the "accent" to replace.
const NEUTRAL_HEXES = new Set([
  "#fff", "#ffffff", "#000", "#000000",
  "#f", "#e", "#111", "#222", "#333", "#444", "#555", "#666",
  "#777", "#888", "#999", "#aaa", "#bbb", "#ccc", "#ddd", "#eee",
  "#f1f5f9", "#e5e7eb", "#d1d5db", "#cbd5e1", "#94a3b8", "#64748b",
  "#475569", "#334155", "#1e293b", "#0f172a", "#0b1020", "#020617",
  "#1f2937", "#111827", "#374151", "#4b5563", "#6b7280", "#9ca3af",
  "#f8fafc", "#f9fafb", "#f3f4f6", "#e0e5ec", "#b8bcc2",
  "#ffffff80", "#ffffffaa", "#ffffffcc", "#ffffff33", "#ffffff55",
  "#00000033", "#00000044", "#0000001a", "#00000022",
])

/**
 * Find the most prominent non-neutral hex colors in a CSS source, ordered by
 * frequency (most-used first). Returns up to `max` hexes (lowercase, with #).
 */
function findAccentColors(css: string, max = 3): string[] {
  const hexRe = /#([0-9a-fA-F]{3,8})\b/g
  const counts = new Map<string, number>()
  const firstSeen = new Map<string, number>()
  let idx = 0
  let m: RegExpExecArray | null
  while ((m = hexRe.exec(css)) !== null) {
    const hex = m[0].toLowerCase()
    if (NEUTRAL_HEXES.has(hex)) {
      idx++
      continue
    }
    // Skip very transparent variants (8-digit hex ending in low alpha).
    if (hex.length === 9) {
      const alpha = parseInt(hex.slice(7, 9), 16)
      if (alpha < 0x55) {
        idx++
        continue
      }
    }
    counts.set(hex, (counts.get(hex) ?? 0) + 1)
    if (!firstSeen.has(hex)) firstSeen.set(hex, idx)
    idx++
  }
  if (counts.size === 0) return []
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || (firstSeen.get(a[0])! - firstSeen.get(b[0])!))
    .slice(0, max)
    .map(([hex]) => hex)
}

/** Replace all occurrences of `from` hex in `css` with `to`, case-insensitive. */
function replaceHex(css: string, from: string, to: string): string {
  // Build a case-insensitive regex for the exact hex (and its #rrggbbaa variants
  // that share the same rgb channels).
  const core = from.slice(1) // without #
  const re = new RegExp(`#${core}(?:[0-9a-fA-F]{2})?\\b`, "g")
  return css.replace(re, to)
}

// --- Tiny HSL helpers for coherent multi-color accent derivation ---

function hexToRgb(hex: string): [number, number, number] | null {
  let h = hex.replace("#", "")
  if (h.length === 3) h = h.split("").map((c) => c + c).join("")
  if (h.length < 6) return null
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return [r, g, b]
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b)
  let h = 0, s = 0
  const l = (max + min) / 2
  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break
      case g: h = (b - r) / d + 2; break
      default: h = (r - g) / d + 4; break
    }
    h /= 6
  }
  return [h * 360, s * 100, l * 100]
}

function hslToHex(h: number, s: number, l: number): string {
  h = ((h % 360) + 360) % 360
  s /= 100; l /= 100
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  let r = 0, g = 0, b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  const to2 = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, "0")
  return `#${to2(r)}${to2(g)}${to2(b)}`
}

/**
 * Derive a replacement color for an original effect hex, given the user-chosen
 * accent. The accent's hue is rotated by the angular distance between the
 * original dominant color and this color, so a multi-stop gradient recolors
 * coherently rather than collapsing to a single flat color.
 */
function deriveAccentColor(originalHex: string, dominantHex: string, accent: string): string {
  const origRgb = hexToRgb(originalHex)
  const domRgb = hexToRgb(dominantHex)
  const accRgb = hexToRgb(accent)
  if (!origRgb || !domRgb || !accRgb) return accent
  const [, , ol] = rgbToHsl(...origRgb)
  const [dh, ds, dl] = rgbToHsl(...domRgb)
  const [ah, as, al] = rgbToHsl(...accRgb)
  // Hue shift = accent hue - dominant hue, applied to the original's hue.
  const shift = ah - dh
  const newH = origRgb === domRgb ? ah : (rgbToHsl(...origRgb)[0] + shift)
  // Keep the accent's saturation, blend lightness a bit toward original for nuance.
  const newS = Math.round((as + ds) / 2)
  const newL = Math.round((al + ol) / 2)
  return hslToHex(newH, newS, newL)
}

/**
 * Renders a live CSS effect demo by injecting the effect's CSS into a scoped
 * <style> tag and rendering the effect's HTML inside a container.
 *
 * CSS scoping: every effect ships with uniquely-prefixed class names so there
 * is no cross-effect collision even when many previews live on the page at once.
 *
 * Accent injection: when `accent` is set, the effect's dominant non-neutral hex
 * color is rewritten to the accent in the injected CSS (scoped to this instance
 * via a wrapper class), so the live preview recolors without mutating the
 * source CSS shown in the code panel.
 */
export function EffectPreview({
  effect,
  className,
  interactive = true,
  backdrop = "auto",
  scale = 1,
  accent,
}: EffectPreviewProps) {
  const scopeId = React.useId().replace(/[:]/g, "")
  const styleRef = React.useRef<HTMLStyleElement | null>(null)
  const containerRef = React.useRef<HTMLDivElement | null>(null)

  // Compute the recolored CSS when an accent is provided. Recolors up to 5
  // non-neutral hexes, deriving coherent hue-shifted variants for the
  // non-dominant ones so multi-stop gradients don't collapse to flat color.
  const injectedCss = React.useMemo(() => {
    if (!accent) return effect.css
    const accents = findAccentColors(effect.css, 5)
    if (accents.length === 0) return effect.css
    const dominant = accents[0]
    let css = effect.css
    for (const orig of accents) {
      const replacement = orig === dominant ? accent : deriveAccentColor(orig, dominant, accent)
      css = replaceHex(css, orig, replacement)
    }
    return css
  }, [effect.css, accent])

  // Inject (and clean up) the CSS. Re-runs when the accent changes so the
  // preview recolors live.
  React.useEffect(() => {
    const style = document.createElement("style")
    style.setAttribute("data-effect", effect.id)
    style.setAttribute("data-scope", scopeId)
    style.textContent = injectedCss
    document.head.appendChild(style)
    styleRef.current = style
    return () => {
      style.remove()
    }
  }, [effect.id, scopeId, injectedCss])

  // For the spotlight card, track pointer position to drive the glow.
  const handleMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const rect = el.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * 100
    const y = ((e.clientY - rect.top) / rect.height) * 100
    el.style.setProperty("--x", `${x}%`)
    el.style.setProperty("--y", `${y}%`)
    const target = el.querySelector<HTMLElement>(".sp-card") ?? el
    ;(target as HTMLElement).style.setProperty("--x", `${x}%`)
    ;(target as HTMLElement).style.setProperty("--y", `${y}%`)
  }

  const resolvedBg = backdrop === "auto" ? effect.bg ?? "light" : backdrop

  // Playground: apply a scale transform + accent CSS var on the inner wrapper.
  const wrapperStyle: React.CSSProperties = {
    transform: scale === 1 ? undefined : `scale(${scale})`,
    transformOrigin: "center center",
    ...(accent ? ({ ["--fx-accent" as string]: accent } as React.CSSProperties) : {}),
  }

  return (
    <div
      className={`flex items-center justify-center p-6 ${bgClasses[resolvedBg] ?? "bg-white"} ${className ?? ""}`}
      onMouseMove={effect.id === "card-spotlight" ? handleMove : undefined}
      style={{ pointerEvents: interactive ? "auto" : "none" }}
    >
      <div
        ref={containerRef}
        data-scope={scopeId}
        style={wrapperStyle}
        dangerouslySetInnerHTML={{ __html: effect.html }}
      />
    </div>
  )
}
