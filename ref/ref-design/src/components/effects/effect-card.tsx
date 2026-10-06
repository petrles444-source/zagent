"use client"

import * as React from "react"
import { Code2, Maximize2, Star } from "lucide-react"
import type { CSSEffect } from "@/data/effects"
import { EffectPreview } from "./effect-preview"
import { cn } from "@/lib/utils"

interface EffectCardProps {
  effect: CSSEffect
  index?: number
  onOpen: (effect: CSSEffect) => void
  isFavorite?: boolean
  onToggleFavorite?: (id: string) => void
}

export function EffectCard({
  effect,
  index = 0,
  onOpen,
  isFavorite = false,
  onToggleFavorite,
}: EffectCardProps) {
  return (
    <div
      className="fx-fade-up group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-xl hover:shadow-primary/5"
      style={{ animationDelay: `${Math.min(index * 35, 400)}ms` }}
    >
      {/* Live preview area */}
      <div className="relative h-44 w-full overflow-hidden border-b border-border">
        <EffectPreview effect={effect} className="h-full w-full" />

        {/* Top-left category badge */}
        <span className="absolute left-3 top-3 z-10 rounded-full bg-background/85 px-2.5 py-0.5 text-[11px] font-medium capitalize text-foreground/80 shadow-sm backdrop-blur">
          {effect.category}
        </span>

        {/* Top-right favorite (star) button — always visible if favorited */}
        {onToggleFavorite && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onToggleFavorite(effect.id)
            }}
            aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
            aria-pressed={isFavorite}
            className={cn(
              "absolute right-3 top-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-full border backdrop-blur transition-all duration-200 hover:scale-110",
              isFavorite
                ? "border-amber-400/50 bg-amber-400/15 text-amber-400 shadow-sm shadow-amber-500/20"
                : "border-border bg-background/80 text-foreground/60 opacity-0 group-hover:opacity-100 hover:text-amber-400"
            )}
          >
            <Star
              className={cn("h-4 w-4 transition-all", isFavorite && "fill-amber-400")}
            />
          </button>
        )}

        {/* Hover overlay with quick actions */}
        <div className="pointer-events-none absolute inset-0 flex items-end justify-start gap-2 bg-gradient-to-t from-black/45 via-transparent to-transparent p-3 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <button
            type="button"
            onClick={() => onOpen(effect)}
            className="pointer-events-auto inline-flex items-center gap-1.5 rounded-md bg-white/90 px-2.5 py-1.5 text-xs font-semibold text-gray-900 shadow-sm backdrop-blur transition hover:bg-white"
          >
            <Maximize2 className="h-3.5 w-3.5" />
            Expand
          </button>
        </div>
      </div>

      {/* Footer */}
      <button
        type="button"
        onClick={() => onOpen(effect)}
        className="flex flex-1 flex-col gap-1 p-4 text-left"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold leading-tight">
            {effect.name}
          </h3>
          <Code2 className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:text-primary" />
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {effect.description}
        </p>
        <div className="mt-2 flex flex-wrap gap-1">
          {effect.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </div>
      </button>
    </div>
  )
}
