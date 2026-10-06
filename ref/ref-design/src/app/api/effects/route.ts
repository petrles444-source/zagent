import { NextResponse } from "next/server"
import { EFFECTS, CATEGORIES, getEffectsByCategory } from "@/data/effects"

// Search params are read per-request, so this route must stay dynamic.
export const dynamic = "force-dynamic"

// Curated set of greyscale/neutral hexes that should never count as a
// searchable accent color.
const NEUTRAL_HEXES = new Set([
  "#fff", "#ffffff", "#000", "#000000",
  "#111", "#222", "#333", "#444", "#555", "#666", "#777", "#888",
  "#999", "#aaa", "#bbb", "#ccc", "#ddd", "#eee",
  "#f1f5f9", "#e5e7eb", "#d1d5db", "#cbd5e1", "#94a3b8", "#64748b",
  "#475569", "#334155", "#1e293b", "#0f172a", "#0b1020", "#020617",
  "#1f2937", "#111827", "#374151", "#4b5563", "#6b7280", "#9ca3af",
  "#f8fafc", "#f9fafb", "#f3f4f6", "#e0e5ec", "#b8bcc2",
  "#ffffff80", "#ffffffaa", "#ffffffcc", "#ffffff33", "#ffffff55",
  "#00000033", "#00000044", "#0000001a", "#00000022",
])

/** Extract non-neutral hex colors used in an effect's CSS, lowercased. */
function effectColors(css: string): Set<string> {
  const out = new Set<string>()
  const re = /#([0-9a-fA-F]{6})\b/g
  let m: RegExpExecArray | null
  while ((m = re.exec(css)) !== null) {
    const hex = m[0].toLowerCase()
    if (!NEUTRAL_HEXES.has(hex)) out.add(hex)
  }
  return out
}

// Precompute a hex -> effect-ids index once for color search.
const COLOR_INDEX: Map<string, string[]> = (() => {
  const idx = new Map<string, string[]>()
  for (const e of EFFECTS) {
    for (const hex of effectColors(e.css)) {
      const arr = idx.get(hex) ?? []
      arr.push(e.id)
      idx.set(hex, arr)
    }
  }
  return idx
})()

// The top 12 most-used accent colors across the library, for the color-picker.
const TOP_COLORS = (() => {
  const counts = new Map<string, number>()
  for (const [hex, ids] of COLOR_INDEX) counts.set(hex, ids.length)
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([hex]) => hex)
})()

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const category = searchParams.get("category") ?? "all"
  const q = searchParams.get("q")?.toLowerCase().trim() ?? ""
  const color = searchParams.get("color")?.toLowerCase().trim() ?? ""
  const favoritesParam = searchParams.get("favorites") ?? ""
  const recentParam = searchParams.get("recent") ?? ""
  const popularParam = searchParams.get("popular") ?? ""

  // "favorites", "recent", and "popular" are virtual categories whose contents
  // depend on client-supplied ID lists (stored in localStorage).
  const favIds = new Set(
    favoritesParam ? favoritesParam.split(",").filter(Boolean) : []
  )
  const recentIds = recentParam
    ? recentParam.split(",").filter(Boolean)
    : []
  // popularParam is an ordered, most-viewed-first list of ids.
  const popularIds = popularParam
    ? popularParam.split(",").filter(Boolean)
    : []

  let effects: typeof EFFECTS
  if (category === "favorites") {
    effects = EFFECTS.filter((e) => favIds.has(e.id))
  } else if (category === "recent") {
    const byId = new Map(EFFECTS.map((e) => [e.id, e]))
    effects = recentIds
      .map((id) => byId.get(id))
      .filter((e): e is (typeof EFFECTS)[number] => Boolean(e))
  } else if (category === "popular") {
    // Render in most-viewed-first order (as supplied by the client).
    const byId = new Map(EFFECTS.map((e) => [e.id, e]))
    effects = popularIds
      .map((id) => byId.get(id))
      .filter((e): e is (typeof EFFECTS)[number] => Boolean(e))
  } else {
    effects = getEffectsByCategory(category)
  }

  if (color) {
    // Match effects whose CSS contains the requested hex (normalized to 6-digit).
    effects = effects.filter((e) => effectColors(e.css).has(color))
  }

  if (q) {
    effects = effects.filter(
      (e) =>
        e.name.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q) ||
        e.tags.some((t) => t.toLowerCase().includes(q))
    )
  }

  const categories = CATEGORIES.map((c) => ({
    ...c,
    count:
      c.id === "all"
        ? EFFECTS.length
        : EFFECTS.filter((e) => e.category === c.id).length,
  }))
  // Inject the three virtual categories after "all": popular, recent, favorites.
  categories.splice(1, 0, {
    id: "popular",
    name: "Popular",
    icon: "Flame",
    count: popularIds.length,
  })
  categories.splice(2, 0, {
    id: "recent",
    name: "Recent",
    icon: "History",
    count: recentIds.length,
  })
  categories.splice(3, 0, {
    id: "favorites",
    name: "Favorites",
    icon: "Heart",
    count: favIds.size,
  })

  return NextResponse.json({
    effects,
    categories,
    total: EFFECTS.length,
    filtered: effects.length,
    favoritesCount: favIds.size,
    recentCount: recentIds.length,
    popularCount: popularIds.length,
    topColors: TOP_COLORS,
  })
}
