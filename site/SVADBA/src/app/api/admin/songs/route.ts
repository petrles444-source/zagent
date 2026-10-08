import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * PATCH /api/admin/songs?token=<password>
 * Body: { id, action: "play" | "stop" }
 *
 * Sets a song as "now playing" (clears any previously-playing song so
 * only one is active at a time). Protected by WEDDING_ADMIN_TOKEN.
 */
export async function PATCH(req: NextRequest) {
  try {
    const expected = process.env.WEDDING_ADMIN_TOKEN;
    if (!expected) {
      return NextResponse.json(
        { error: "Админ-доступ не настроен" },
        { status: 503 }
      );
    }
    const token = req.nextUrl.searchParams.get("token") ?? "";
    if (!token || !timingSafeEqual(token, expected)) {
      return NextResponse.json({ error: "Неверный пароль" }, { status: 401 });
    }

    const body = await req.json();
    const id = String(body.id ?? "");
    const action = String(body.action ?? "");
    if (!id || !["play", "stop"].includes(action)) {
      return NextResponse.json(
        { error: "Укажите id и действие (play/stop)" },
        { status: 400 }
      );
    }

    if (action === "play") {
      // clear any previously playing song, then set this one
      await db.songRequest.updateMany({
        where: { nowPlaying: true },
        data: { nowPlaying: false },
      });
      const updated = await db.songRequest.update({
        where: { id },
        data: { nowPlaying: true },
        select: { id: true, nowPlaying: true },
      });
      return NextResponse.json({ ok: true, item: updated });
    }
    // stop
    const stopped = await db.songRequest.update({
      where: { id },
      data: { nowPlaying: false },
      select: { id: true, nowPlaying: true },
    });
    return NextResponse.json({ ok: true, item: stopped });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось обновить трек", detail: String(e) },
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
