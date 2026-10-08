import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * PATCH /api/admin/photos — approve / un-approve / delete a photo.
 * Body: { id, action: "approve" | "unapprove" | "delete" }
 * Protected by WEDDING_ADMIN_TOKEN (constant-time compare).
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
    if (!id || !["approve", "unapprove", "delete"].includes(action)) {
      return NextResponse.json(
        { error: "Укажите id и действие (approve/unapprove/delete)" },
        { status: 400 }
      );
    }

    if (action === "delete") {
      await db.photoWall.delete({ where: { id } });
      return NextResponse.json({ ok: true, deleted: id });
    }
    const updated = await db.photoWall.update({
      where: { id },
      data: { approved: action === "approve" },
      select: { id: true, approved: true },
    });
    return NextResponse.json({ ok: true, item: updated });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось обновить фото", detail: String(e) },
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
