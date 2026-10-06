"use client"

import * as React from "react"
import { useTheme } from "next-themes"

export type CodeThemePref = "auto" | "dark" | "light"
export type ResolvedCodeTheme = "dark" | "light"

const STORAGE_KEY = "cssfx:code-theme"
const EVENT = "cssfx:code-theme-changed"

function readPref(): CodeThemePref {
  if (typeof window === "undefined") return "auto"
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    if (v === "light" || v === "dark") return v
    return "auto"
  } catch {
    return "auto"
  }
}

function writePref(t: CodeThemePref) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, t)
    window.dispatchEvent(new Event(EVENT))
  } catch {
    // ignore
  }
}

/**
 * useCodeTheme — a localStorage-backed code-theme preference.
 *
 * Supports three modes:
 *  - "auto"  (default): follows the page theme (next-themes resolvedTheme).
 *  - "dark" / "light": explicit override, independent of the page theme.
 *
 * Cycles auto → dark → light → auto on `toggle`.
 * Syncs across components/tabs via a custom event + the storage event.
 */
export function useCodeTheme() {
  const [pref, setPref] = React.useState<CodeThemePref>("auto")
  const [hydrated, setHydrated] = React.useState(false)
  const { resolvedTheme } = useTheme()

  React.useEffect(() => {
    setPref(readPref())
    setHydrated(true)
    const onChange = () => setPref(readPref())
    window.addEventListener(EVENT, onChange)
    window.addEventListener("storage", onChange)
    return () => {
      window.removeEventListener(EVENT, onChange)
      window.removeEventListener("storage", onChange)
    }
  }, [])

  // Resolve the effective theme. In "auto" mode, follow the page theme once
  // hydrated; before hydration default to dark to match the SSR markup.
  const theme: ResolvedCodeTheme =
    pref === "auto"
      ? hydrated
        ? resolvedTheme === "light"
          ? "light"
          : "dark"
        : "dark"
      : pref

  const toggle = React.useCallback(() => {
    setPref((prev) => {
      const order: CodeThemePref[] = ["auto", "dark", "light"]
      const idx = order.indexOf(prev)
      const next = order[(idx + 1) % order.length]
      writePref(next)
      return next
    })
  }, [])

  const setExplicit = React.useCallback((t: ResolvedCodeTheme) => {
    writePref(t)
    setPref(t)
  }, [])

  const setAuto = React.useCallback(() => {
    writePref("auto")
    setPref("auto")
  }, [])

  return { theme, pref, toggle, setExplicit, setAuto, hydrated }
}
