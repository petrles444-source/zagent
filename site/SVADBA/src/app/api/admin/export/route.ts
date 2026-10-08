import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

/**
 * GET /api/admin/export?token=<password>&type=rsvp|guestbook|songs
 *
 * Streams a CSV file of the requested collection. The password is compared
 * against the WEDDING_ADMIN_TOKEN env var (constant-time). If the env var
 * is unset, admin access is disabled and a 503 is returned.
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

    const type = req.nextUrl.searchParams.get("type") ?? "rsvp";
    const sp = req.nextUrl.searchParams;

    if (type === "rsvp") {
      const items = await db.rsvp.findMany({ orderBy: { createdAt: "desc" } });
      const rows: string[][] = [
        [
          "Имя",
          "Email",
          "Телефон",
          "Придёт",
          "Гостей",
          "Меню",
          "Напиток",
          "Сообщение",
          "Создано",
        ],
        ...items.map((r) => [
          r.name,
          r.email ?? "",
          r.phone ?? "",
          r.attending,
          String(r.guests),
          r.meal ?? "",
          r.drink ?? "",
          (r.message ?? "").replace(/\n/g, " "),
          r.createdAt.toISOString(),
        ]),
      ];
      return csv(rows, "rsvp");
    }

    if (type === "guestbook") {
      const items = await db.guestbook.findMany({ orderBy: { createdAt: "desc" } });
      const rows: string[][] = [
        ["Имя", "Сообщение", "Придёт", "Лайки", "Создано"],
        ...items.map((g) => [
          g.name,
          (g.message ?? "").replace(/\n/g, " "),
          g.attend ?? "",
          String(g.likes ?? 0),
          g.createdAt.toISOString(),
        ]),
      ];
      return csv(rows, "guestbook");
    }

    if (type === "songs") {
      const items = await db.songRequest.findMany({ orderBy: { createdAt: "desc" } });
      const rows: string[][] = [
        ["Имя", "Песня", "Исполнитель", "Создано"],
        ...items.map((s) => [
          s.name,
          s.title,
          s.artist ?? "",
          s.createdAt.toISOString(),
        ]),
      ];
      return csv(rows, "songs");
    }

    void sp; // satisfy unused
    return NextResponse.json({ error: "Неизвестный тип экспорта" }, { status: 400 });
  } catch (e) {
    return NextResponse.json(
      { error: "Экспорт не удался", detail: String(e) },
      { status: 500 }
    );
  }
}

function csv(rows: string[][], name: string) {
  const body = rows
    .map((r) => r.map(csvEscape).join(";"))
    .join("\r\n");
  // Prepend BOM so Excel reads UTF-8 correctly.
  const buf = "\uFEFF" + body;
  return new NextResponse(buf, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${name}-${new Date()
        .toISOString()
        .slice(0, 10)}.csv"`,
    },
  });
}

function csvEscape(v: string): string {
  if (v == null) return "";
  const needsQuote = /[";\n\r]/.test(v);
  const escaped = v.replace(/"/g, '""');
  return needsQuote ? `"${escaped}"` : escaped;
}

/** Constant-time string comparison to resist timing attacks. */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    // still do the work to keep timing similar
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
