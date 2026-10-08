import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const items = await db.songRequest.findMany({
      orderBy: { createdAt: "desc" },
      take: 100,
    });
    return NextResponse.json({ items });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить список песен", detail: String(e) },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const name = String(body.name ?? "").trim();
    const title = String(body.title ?? "").trim();
    if (!name) {
      return NextResponse.json({ error: "Укажите ваше имя" }, { status: 400 });
    }
    if (!title) {
      return NextResponse.json({ error: "Укажите название песни" }, { status: 400 });
    }
    const artist = optString(body.artist);

    const created = await db.songRequest.create({
      data: { name, title, artist },
    });
    return NextResponse.json({ ok: true, item: created }, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось сохранить заявку", detail: String(e) },
      { status: 500 }
    );
  }
}

function optString(v: unknown) {
  const s = String(v ?? "").trim();
  return s.length ? s : null;
}
