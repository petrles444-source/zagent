"use client"

import * as React from "react"

const STORAGE_KEY = "cssfx:recent"
const MAX_RECENT = 12

function readRecent(): string[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw) as string[]
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function writeRecent(ids: string[]) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
    window.dispatchEvent(new Event("cssfx:recent-changed"))
  } catch {
    // ignore
  }
}

/**
 * useRecent — track the most-recently-viewed effect IDs in localStorage
 * (most-recent-first, deduped, capped at MAX_RECENT). Syncs across
 * components/tabs via a custom event + the storage event.
 */
export function useRecent() {
  const [recent, setRecent] = React.useState<string[]>(() => [])
  const [hydrated, setHydrated] = React.useState(false)

  React.useEffect(() => {
    setRecent(readRecent())
    setHydrated(true)
    const onChange = () => setRecent(readRecent())
    window.addEventListener("cssfx:recent-changed", onChange)
    window.addEventListener("storage", onChange)
    return () => {
      window.removeEventListener("cssfx:recent-changed", onChange)
      window.removeEventListener("storage", onChange)
    }
  }, [])

  const push = React.useCallback((id: string) => {
    setRecent((prev) => {
      const next = [id, ...prev.filter((x) => x !== id)].slice(0, MAX_RECENT)
      writeRecent(next)
      return next
    })
  }, [])

  const clear = React.useCallback(() => {
    writeRecent([])
    setRecent([])
  }, [])

  return { recent, push, clear, hydrated, count: recent.length }
}
