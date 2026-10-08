import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const items = await db.loveLock.findMany({
      orderBy: { createdAt: "desc" },
      take: 200,
    });
    return NextResponse.json({ items });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить замки", detail: String(e) },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const initials = String(body.initials ?? "").trim().toUpperCase().slice(0, 4);
    if (!initials || initials.length < 2) {
      return NextResponse.json(
        { error: "Введите инициалы (минимум 2 буквы)" },
        { status: 400 }
      );
    }
    const message = body.message
      ? String(body.message).trim().slice(0, 120)
      : null;
    const color = normalizeColor(body.color);

    const created = await db.loveLock.create({
      data: { initials, message, color },
    });
    return NextResponse.json({ ok: true, item: created }, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось повесить замок", detail: String(e) },
      { status: 500 }
    );
  }
}

function normalizeColor(v: unknown): string {
  const s = String(v ?? "").toLowerCase();
  if (["gold", "blush", "ivory", "champagne"].includes(s)) return s;
  return "gold";
}
