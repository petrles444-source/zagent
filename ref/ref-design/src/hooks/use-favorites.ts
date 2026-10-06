"use client"

import * as React from "react"

const STORAGE_KEY = "cssfx:favorites"

function readFavorites(): Set<string> {
  if (typeof window === "undefined") return new Set()
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as string[]
    return new Set(arr)
  } catch {
    return new Set()
  }
}

function writeFavorites(favs: Set<string>) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(favs)))
    // Notify other components / tabs of the change.
    window.dispatchEvent(new Event("cssfx:favorites-changed"))
  } catch {
    // ignore quota / private mode errors
  }
}

/**
 * useFavorites — a localStorage-backed set of favorite effect IDs.
 * Keeps state in sync across components and browser tabs via a custom event
 * + the storage event.
 */
export function useFavorites() {
  const [favorites, setFavorites] = React.useState<Set<string>>(() => new Set())
  const [hydrated, setHydrated] = React.useState(false)

  React.useEffect(() => {
    setFavorites(readFavorites())
    setHydrated(true)

    const onChange = () => setFavorites(readFavorites())
    window.addEventListener("cssfx:favorites-changed", onChange)
    window.addEventListener("storage", onChange)
    return () => {
      window.removeEventListener("cssfx:favorites-changed", onChange)
      window.removeEventListener("storage", onChange)
    }
  }, [])

  const toggle = React.useCallback((id: string) => {
    setFavorites((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      writeFavorites(next)
      return next
    })
  }, [])

  const has = React.useCallback((id: string) => favorites.has(id), [favorites])

  const clear = React.useCallback(() => {
    writeFavorites(new Set())
    setFavorites(new Set())
  }, [])

  return { favorites, toggle, has, clear, hydrated, count: favorites.size }
}
