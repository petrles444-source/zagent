import { NextRequest, NextResponse } from "next/server";
import { wedding } from "@/lib/wedding-config";

export const dynamic = "force-dynamic";

/**
 * GET /api/tables?q=<name>
 * Searches every table's guest list for a (case-insensitive, partial) match
 * of the surname/name supplied. Returns the matching table + the matched
 * guest + the full list of tables (so the UI can show a "browse" fallback).
 *
 * No persistence needed — seating is config-driven, so this route runs
 * purely in memory and is fast & stateless.
 */
export async function GET(req: NextRequest) {
  try {
    const q = (req.nextUrl.searchParams.get("q") ?? "").trim().toLowerCase();

    const list = wedding.tables.map((t) => ({
      id: t.id,
      name: t.name,
      subtitle: t.subtitle,
      total: t.guests.length,
    }));

    if (!q || q.length < 2) {
      return NextResponse.json({ query: q || null, match: null, tables: list });
    }

    // Find the first table that contains a guest whose name contains the query.
    let match: {
      table: (typeof wedding.tables)[number];
      guest: string;
    } | null = null;

    for (const t of wedding.tables) {
      const hit = t.guests.find((g) => g.toLowerCase().includes(q));
      if (hit) {
        match = { table: t, guest: hit };
        break;
      }
    }

    return NextResponse.json({
      query: q,
      match: match
        ? {
            tableId: match.table.id,
            tableName: match.table.name,
            subtitle: match.table.subtitle,
            guest: match.guest,
            seatMates: match.table.guests.filter((g) => g !== match!.guest),
            tableGuests: match.table.guests,
          }
        : null,
      tables: list,
    });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось найти стол", detail: String(e) },
      { status: 500 }
    );
  }
}
