import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Max base64 image size — ~1.5 MB after client-side resize. */
const MAX_IMAGE_BYTES = 1_600_000;

/**
 * GET /api/photos — returns approved photos, newest first.
 * Optional ?pending=1 (admin only — protected by the admin summary route's
 * token check downstream) returns unapproved photos.
 */
export async function GET(req: NextRequest) {
  try {
    const pending = req.nextUrl.searchParams.get("pending") === "1";
    const items = await db.photoWall.findMany({
      where: pending ? {} : { approved: true },
      orderBy: { createdAt: "desc" },
      take: 120,
    });
    return NextResponse.json({ items });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить фото", detail: String(e) },
      { status: 500 }
    );
  }
}

/**
 * POST /api/photos — submit a new photo for moderation.
 * Body: { guestName, caption?, image } where `image` is a base64 data URL
 * (data:image/jpeg;base64,...). Photos are stored unapproved and require
 * admin moderation before appearing on the wall.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const guestName = String(body.guestName ?? "").trim();
    if (!guestName) {
      return NextResponse.json({ error: "Укажите ваше имя" }, { status: 400 });
    }
    const image = String(body.image ?? "");
    if (!image.startsWith("data:image/")) {
      return NextResponse.json(
        { error: "Изображение не передано" },
        { status: 400 }
      );
    }
    if (image.length > MAX_IMAGE_BYTES) {
      return NextResponse.json(
        { error: "Изображение слишком большое (макс. 1.5 МБ)" },
        { status: 400 }
      );
    }
    const caption = body.caption
      ? String(body.caption).trim().slice(0, 200)
      : null;

    const created = await db.photoWall.create({
      data: { guestName, caption, image, approved: false },
    });
    return NextResponse.json(
      { ok: true, id: created.id },
      { status: 201 }
    );
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось сохранить фото", detail: String(e) },
      { status: 500 }
    );
  }
}
