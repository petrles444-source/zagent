"use client"

import * as React from "react"

const STORAGE_KEY = "cssfx:views"
const MAX_TRACKED = 30

function readViews(): Record<string, number> {
  if (typeof window === "undefined") return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const obj = JSON.parse(raw)
    return obj && typeof obj === "object" ? obj : {}
  } catch {
    return {}
  }
}

function writeViews(views: Record<string, number>) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(views))
    window.dispatchEvent(new Event("cssfx:views-changed"))
  } catch {
    // ignore
  }
}

/**
 * useViews — a localStorage-backed per-effect open counter.
 *
 * Unlike favorites/recent (sets/lists), this stores a `{ [id]: count }` map.
 * `recordView(id)` increments the count for an effect. The "popular" virtual
 * category surfaces effects ordered by descending view count (most-viewed
 * first), capped at MAX_TRACKED entries to keep localStorage tidy.
 */
export function useViews() {
  const [views, setViews] = React.useState<Record<string, number>>(() => ({}))
  const [hydrated, setHydrated] = React.useState(false)

  React.useEffect(() => {
    setViews(readViews())
    setHydrated(true)
    const onChange = () => setViews(readViews())
    window.addEventListener("cssfx:views-changed", onChange)
    window.addEventListener("storage", onChange)
    return () => {
      window.removeEventListener("cssfx:views-changed", onChange)
      window.removeEventListener("storage", onChange)
    }
  }, [])

  const recordView = React.useCallback((id: string) => {
    setViews((prev) => {
      const next = { ...prev, [id]: (prev[id] ?? 0) + 1 }
      // Cap the map size: if it grows beyond MAX_TRACKED, drop the least-viewed.
      const entries = Object.entries(next)
      if (entries.length > MAX_TRACKED) {
        entries.sort((a, b) => a[1] - b[1])
        entries.splice(0, entries.length - MAX_TRACKED)
      }
      const capped: Record<string, number> = {}
      for (const [k, v] of entries) capped[k] = v
      writeViews(capped)
      return capped
    })
  }, [])

  // Most-viewed-first ordered list of ids with a count > 0.
  const popularIds = React.useMemo(() => {
    return Object.entries(views)
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([id]) => id)
  }, [views])

  const count = popularIds.length
  const viewCount = (id: string) => views[id] ?? 0

  return { views, popularIds, recordView, count, viewCount, hydrated }
}
