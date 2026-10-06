"use client"

import * as React from "react"
import { Palette, RotateCcw, SlidersHorizontal, Square } from "lucide-react"
import type { PreviewBackdrop } from "./effect-preview"
import { cn } from "@/lib/utils"

interface PlaygroundPanelProps {
  scale: number
  onScaleChange: (v: number) => void
  accent: string
  onAccentChange: (v: string) => void
  backdrop: PreviewBackdrop
  onBackdropChange: (v: PreviewBackdrop) => void
  onReset: () => void
}

const BACKDROPS: { id: PreviewBackdrop; label: string }[] = [
  { id: "auto", label: "Auto" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
  { id: "gradient", label: "Gradient" },
  { id: "checker", label: "Checker" },
]

const ACCENT_SWATCHES = [
  "#6366f1",
  "#ec4899",
  "#22c55e",
  "#f59e0b",
  "#06b6d4",
  "#ef4444",
  "#8b5cf6",
  "#0ea5e9",
]

export function PlaygroundPanel({
  scale,
  onScaleChange,
  accent,
  onAccentChange,
  backdrop,
  onBackdropChange,
  onReset,
}: PlaygroundPanelProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-border bg-muted/30 px-4 py-2.5">
      {/* Backdrop switcher */}
      <div className="flex items-center gap-1.5">
        <Square className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Backdrop
        </span>
        <div className="flex items-center gap-0.5 rounded-md bg-background p-0.5 ring-1 ring-border">
          {BACKDROPS.map((b) => (
            <button
              key={b.id}
              type="button"
              onClick={() => onBackdropChange(b.id)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium transition",
                backdrop === b.id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* Scale slider */}
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Scale
        </span>
        <input
          type="range"
          min={0.5}
          max={1.5}
          step={0.05}
          value={scale}
          onChange={(e) => onScaleChange(parseFloat(e.target.value))}
          className="fx-range h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-muted accent-primary"
          aria-label="Effect scale"
        />
        <span className="w-9 text-[11px] tabular-nums text-muted-foreground">
          {scale.toFixed(2)}×
        </span>
      </div>

      {/* Accent picker */}
      <div className="flex items-center gap-2">
        <Palette className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Accent
        </span>
        <div className="flex items-center gap-1">
          {ACCENT_SWATCHES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onAccentChange(accent === c ? "" : c)}
              className={cn(
                "h-4 w-4 rounded-full ring-2 ring-offset-1 ring-offset-background transition",
                accent === c ? "ring-foreground" : "ring-transparent hover:ring-border"
              )}
              style={{ backgroundColor: c }}
              aria-label={`Set accent ${c}`}
            />
          ))}
          <input
            type="color"
            value={accent || "#6366f1"}
            onChange={(e) => onAccentChange(e.target.value)}
            className="h-5 w-5 cursor-pointer rounded border-0 bg-transparent p-0"
            aria-label="Custom accent color"
          />
        </div>
      </div>

      {/* Reset */}
      <button
        type="button"
        onClick={onReset}
        className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <RotateCcw className="h-3 w-3" />
        Reset
      </button>
    </div>
  )
}
