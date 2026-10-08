import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const items = await db.guestbook.findMany({
      orderBy: { createdAt: "desc" },
      take: 100,
    });
    return NextResponse.json({ items });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить пожелания", detail: String(e) },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const name = String(body.name ?? "").trim();
    const message = String(body.message ?? "").trim();
    if (!name) {
      return NextResponse.json({ error: "Укажите ваше имя" }, { status: 400 });
    }
    if (!message) {
      return NextResponse.json({ error: "Напишите хотя бы пару тёплых слов" }, { status: 400 });
    }
    if (message.length > 1000) {
      return NextResponse.json({ error: "Сообщение слишком длинное (макс. 1000 символов)" }, { status: 400 });
    }
    const attend = normalizeAttending(body.attend);

    const created = await db.guestbook.create({
      data: { name, message, attend, likes: 0 },
    });
    return NextResponse.json({ ok: true, item: created }, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось сохранить пожелание", detail: String(e) },
      { status: 500 }
    );
  }
}

/**
 * PATCH /api/guestbook — like / unlike a wish.
 * Body: { id: string, delta?: +1 | -1 }  (defaults to +1)
 * Uses an in-memory Set of liked ids persisted to localStorage on the client
 * to prevent duplicate likes from the same browser.
 */
export async function PATCH(req: NextRequest) {
  try {
    const body = await req.json();
    const id = String(body.id ?? "");
    if (!id) {
      return NextResponse.json({ error: "Укажите id пожелания" }, { status: 400 });
    }
    const delta = Number(body.delta) === -1 ? -1 : 1;

    const updated = await db.guestbook.update({
      where: { id },
      data: { likes: { increment: delta } },
      select: { id: true, likes: true },
    });
    return NextResponse.json({ ok: true, item: updated });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось обновить лайк", detail: String(e) },
      { status: 500 }
    );
  }
}

function normalizeAttending(v: unknown) {
  const s = String(v ?? "").toLowerCase();
  if (s === "yes" || s === "no" || s === "maybe") return s;
  return null;
}
