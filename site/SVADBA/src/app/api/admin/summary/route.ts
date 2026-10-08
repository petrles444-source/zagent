import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * GET /api/admin/summary?token=<password>
 *
 * Returns aggregated stats + recent submissions for the admin dashboard.
 * Uses the same WEDDING_ADMIN_TOKEN gate as the export route.
 */
export async function GET(req: NextRequest) {
  try {
    const expected = process.env.WEDDING_ADMIN_TOKEN;
    if (!expected) {
      return NextResponse.json(
        { error: "Админ-доступ не настроен (WEDDING_ADMIN_TOKEN не задан)" },
        { status: 503 }
      );
    }
    const token = req.nextUrl.searchParams.get("token") ?? "";
    if (!token || !timingSafeEqual(token, expected)) {
      return NextResponse.json({ error: "Неверный пароль" }, { status: 401 });
    }

    const [rsvps, guestbook, songs] = await Promise.all([
      db.rsvp.findMany({ orderBy: { createdAt: "desc" }, take: 200 }),
      db.guestbook.findMany({ orderBy: { createdAt: "desc" }, take: 200 }),
      db.songRequest.findMany({ orderBy: { createdAt: "desc" }, take: 200 }),
    ]);

    const rsvpStats = {
      yes: rsvps.filter((r) => r.attending === "yes").length,
      no: rsvps.filter((r) => r.attending === "no").length,
      maybe: rsvps.filter((r) => r.attending === "maybe").length,
      totalGuests: rsvps
        .filter((r) => r.attending === "yes")
        .reduce((sum, r) => sum + r.guests, 0),
      responses: rsvps.length,
    };

    const mealBreakdown = rsvps.reduce<Record<string, number>>((acc, r) => {
      const k = r.meal ?? "—";
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {});
    const drinkBreakdown = rsvps.reduce<Record<string, number>>((acc, r) => {
      const k = r.drink ?? "—";
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {});

    return NextResponse.json({
      stats: {
        rsvp: rsvpStats,
        guestbook: { count: guestbook.length, likes: guestbook.reduce((s, g) => s + (g.likes ?? 0), 0) },
        songs: { count: songs.length },
      },
      breakdowns: { meal: mealBreakdown, drink: drinkBreakdown },
      rsvps,
      guestbook,
      songs,
      token, // echoed so the client can use it for download links
    });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить сводку", detail: String(e) },
      { status: 500 }
    );
  }
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    let _ = 0;
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      _ ^= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
    }
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}
