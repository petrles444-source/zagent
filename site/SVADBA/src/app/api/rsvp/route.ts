import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const items = await db.rsvp.findMany({
      orderBy: { createdAt: "desc" },
      take: 200,
    });
    const stats = await computeStats(items);
    return NextResponse.json({ items, stats });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось получить список RSVP", detail: String(e) },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const name = String(body.name ?? "").trim();
    if (!name) {
      return NextResponse.json({ error: "Укажите ваше имя" }, { status: 400 });
    }
    const attending = normalizeAttending(body.attending);
    const guests = clampInt(body.guests, 1, 10, 1);
    const meal = normalizeChoice(body.meal, ["regular", "vegetarian", "vegan", "kids"], null);
    const drink = normalizeChoice(body.drink, ["wine", "champagne", "strong", "none"], null);
    const email = optString(body.email);
    const phone = optString(body.phone);
    const message = optString(body.message);

    const created = await db.rsvp.create({
      data: { name, email, phone, attending, guests, meal, drink, message },
    });
    return NextResponse.json({ ok: true, item: created }, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: "Не удалось сохранить ответ", detail: String(e) },
      { status: 500 }
    );
  }
}

async function computeStats(items: { attending: string; guests: number }[]) {
  let yes = 0;
  let no = 0;
  let maybe = 0;
  let totalGuests = 0;
  for (const it of items) {
    if (it.attending === "yes") {
      yes += 1;
      totalGuests += it.guests;
    } else if (it.attending === "no") no += 1;
    else maybe += 1;
  }
  return { yes, no, maybe, totalGuests, responses: items.length };
}

function normalizeAttending(v: unknown) {
  const s = String(v ?? "yes").toLowerCase();
  if (s === "no") return "no";
  if (s === "maybe") return "maybe";
  return "yes";
}
function normalizeChoice<T extends string>(
  v: unknown,
  allowed: T[],
  fallback: T | null
): T | null {
  const s = String(v ?? "").toLowerCase();
  return (allowed as string[]).includes(s) ? (s as T) : fallback;
}
function clampInt(v: unknown, min: number, max: number, dflt: number) {
  const n = Number(v);
  if (!Number.isFinite(n)) return dflt;
  return Math.min(max, Math.max(min, Math.round(n)));
}
function optString(v: unknown) {
  const s = String(v ?? "").trim();
  return s.length ? s : null;
}
