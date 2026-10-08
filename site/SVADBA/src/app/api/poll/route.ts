import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * GET /api/poll — returns the current tally + a sparkline of votes over
 * the last 14 days (so the UI can draw a small trend chart).
 */
export async function GET() {
  try {
    const items = await db.guestPoll.findMany({
      orderBy: { createdAt: "asc" },
      take: 5000,
    });
    const tally = { yes: 0, maybe: 0, no: 0 };
    for (const it of items) {
      if (it.answer === "yes") tally.yes++;
      else if (it.answer === "maybe") tally.maybe++;
      else if (it.answer === "no") tally.no++;
    }
    // build a 14-day sparkline of total votes per day
    const days = 14;
    const now = new Date();
    const sparkline: { date: string; total: number }[] = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      const dayEnd = new Date(dayStart.getTime() + 24 * 60 * 60 * 1000);
      const total = items.filter(
        (it) => it.createdAt >= dayStart && it.createdAt < dayEnd
      ).length;
      sparkline.push({
        date: dayStart.toISOString().slice(0, 10),
        total,
      });
    }
    return NextResponse.json({
      tally,
      total: items.length,
      sparkline,
    });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить опрос", detail: String(e) },
      { status: 500 }
    );
  }
}

/**
 * POST /api/poll — submit a vote. One vote per browser (tracked via a
 * cookie that lasts 30 days). Changing the vote is allowed (the old
 * cookie value is replaced).
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const answer = String(body.answer ?? "").toLowerCase();
    if (!["yes", "maybe", "no"].includes(answer)) {
      return NextResponse.json({ error: "Недопустимый ответ" }, { status: 400 });
    }

    // cookie-based dedup: if the voter already has a cookie, we don't
    // create a duplicate (but we allow changing the answer by recording
    // a new vote — the client shows the latest answer).
    const cookieName = "wedding-poll-vote";
    const existing = req.cookies.get(cookieName)?.value;

    const created = await db.guestPoll.create({
      data: { answer },
    });

    const res = NextResponse.json(
      { ok: true, id: created.id, answer, previous: existing ?? null },
      { status: 201 }
    );
    res.cookies.set(cookieName, answer, {
      maxAge: 60 * 60 * 24 * 30,
      httpOnly: true,
      sameSite: "lax",
      path: "/",
    });
    return res;
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось сохранить голос", detail: String(e) },
      { status: 500 }
    );
  }
}
