"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SectionHeading, Heart, Sprig } from "./ornaments";
import { Reveal } from "./reveal";
import { RsvpQRCode } from "./rsvp-qr";
import { useToast } from "@/hooks/use-toast";
import { resizeImageToDataUrl } from "@/lib/image-resize";
import { cn } from "@/lib/utils";

type Photo = {
  id: string;
  guestName: string;
  caption: string | null;
  image: string;
  createdAt: string;
};

export function PhotoWall() {
  const { toast } = useToast();
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [lightbox, setLightbox] = useState<Photo | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/photos", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setPhotos(data.items ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Escape closes lightbox
  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightbox(null);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [lightbox]);

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      toast({ title: "Выберите изображение", variant: "destructive" });
      return;
    }
    if (f.size > 12 * 1024 * 1024) {
      toast({
        title: "Файл слишком большой",
        description: "Максимальный размер — 12 МБ.",
        variant: "destructive",
      });
      return;
    }
    setFile(f);
    try {
      const resized = await resizeImageToDataUrl(f, 900, 0.78);
      setPreview(resized);
    } catch {
      toast({ title: "Не удалось обработать изображение", variant: "destructive" });
      setPreview(null);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast({ title: "Укажите имя", variant: "destructive" });
      return;
    }
    if (!preview) {
      toast({ title: "Выберите фото", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/photos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          guestName: name.trim(),
          caption: caption.trim() || undefined,
          image: preview,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ title: "Ошибка", description: data?.error, variant: "destructive" });
      } else {
        toast({
          title: "Спасибо!",
          description: "Фото отправлено. Оно появится на стене после проверки.",
        });
        setName("");
        setCaption("");
        setFile(null);
        setPreview(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    } catch {
      toast({ title: "Ошибка сети", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      id="photos"
      className="relative overflow-hidden bg-night py-24 sm:py-32"
    >
      <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
      <div className="absolute inset-0 bg-vignette" aria-hidden="true" />

      <div className="relative mx-auto max-w-6xl px-6">
        <Reveal>
          <SectionHeading
            eyebrow="Живые мгновения"
            title="Стена фото"
            subtitle="Делитесь снимками с вечера — мы добавим их на эту стену после проверки. Пусть ночь останется с нами навсегда."
          />
        </Reveal>

        <div className="mt-14 grid gap-10 lg:grid-cols-[1fr_1.6fr]">
          {/* Upload form */}
          <Reveal>
            <form onSubmit={submit} className="card-luxe rounded-sm p-6 sm:p-8">
              <div className="flex flex-col gap-5">
                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Ваше имя
                  </span>
                  <input
                    className="input-luxe"
                    placeholder="Как вас зовут"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>

                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Подпись (необязательно)
                  </span>
                  <input
                    className="input-luxe"
                    placeholder="Пара слов о кадре…"
                    value={caption}
                    maxLength={200}
                    onChange={(e) => setCaption(e.target.value)}
                  />
                </label>

                <label className="flex flex-col gap-2">
                  <span className="font-playfair text-[0.7rem] uppercase tracking-wide-2 text-gold">
                    Фотография
                  </span>
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    className="group relative flex cursor-pointer flex-col items-center justify-center gap-2 rounded-sm border border-dashed border-gold/30 bg-night/40 p-6 transition-all hover:border-gold/60 hover:bg-gold/5"
                  >
                    {preview ? (
                      <div className="relative w-full">
                        <img
                          src={preview}
                          alt="Предпросмотр"
                          className="mx-auto max-h-48 rounded-sm object-contain"
                        />
                        <span className="mt-2 block text-center font-cormorant text-sm text-ivory-soft/60">
                          Нажмите, чтобы изменить
                        </span>
                      </div>
                    ) : (
                      <>
                        <UploadIcon className="h-8 w-8 text-gold/60 transition-transform group-hover:scale-110" />
                        <span className="font-cormorant text-sm text-ivory-soft/70">
                          Перетащите или нажмите для выбора
                        </span>
                        <span className="font-cormorant text-xs text-ivory-soft/40">
                          JPG / PNG · до 12 МБ
                        </span>
                      </>
                    )}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={onFileChange}
                  />
                </label>

                <div className="flex flex-col items-center gap-2">
                  <div className="ornament-line text-gold">
                    <Heart className="h-3 w-3" />
                  </div>
                  <button type="submit" disabled={submitting} className="btn-luxe disabled:opacity-60">
                    {submitting ? "Отправляем…" : "Отправить фото"}
                  </button>
                  <p className="font-cormorant text-xs text-ivory-soft/40">
                    Фото появится после проверки организатором
                  </p>
                </div>
              </div>
            </form>
          </Reveal>

          {/* Wall */}
          <Reveal delay={150}>
            <div className="relative">
              <div className="mb-4 flex items-center justify-between">
                <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
                  {photos.length > 0
                    ? `${photos.length} ${plural(photos.length, ["снимок", "снимка", "снимков"])}`
                    : "Стена пока пуста"}
                </span>
                <span className="font-cormorant text-sm text-ivory-soft/50">
                  обновлено только что
                </span>
              </div>
              {loading ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div
                      key={i}
                      className="aspect-square animate-pulse rounded-sm border border-gold/10 bg-gold/5"
                    />
                  ))}
                </div>
              ) : photos.length === 0 ? (
                <div className="card-luxe rounded-sm p-12 text-center">
                  <Sprig className="mx-auto h-8 w-8 text-gold/40" />
                  <p className="mt-3 font-cormorant text-lg text-ivory-soft/60">
                    Будьте первым, кто поделится снимком
                  </p>
                  <p className="mt-1 font-cormorant text-sm text-ivory-soft/40">
                    Фотографии появятся здесь после полуночи
                  </p>
                </div>
              ) : (
                <div className="luxe-scroll grid max-h-[40rem] grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
                  {photos.map((p) => (
                    <PhotoTile key={p.id} photo={p} onOpen={() => setLightbox(p)} />
                  ))}
                </div>
              )}
            </div>
          </Reveal>
        </div>
      </div>

      {/* On-site photo-sharing QR */}
      <Reveal delay={200} className="mt-12 flex justify-center">
        <RsvpQRCode variant="photos" />
      </Reveal>

      {/* Lightbox */}
      {lightbox && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-night/95 backdrop-blur-md animate-fade-in"
          onClick={() => setLightbox(null)}
          role="dialog"
          aria-modal="true"
        >
          <button
            onClick={() => setLightbox(null)}
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-gold/40 text-gold transition-all hover:rotate-90 hover:bg-gold/10"
            aria-label="Закрыть"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
          <figure
            className="relative z-10 mx-auto max-h-[88vh] max-w-3xl px-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="frame-gold overflow-hidden">
              <img
                src={lightbox.image}
                alt={lightbox.caption ?? `Фото от ${lightbox.guestName}`}
                className="max-h-[74vh] max-w-full object-contain"
              />
            </div>
            <figcaption className="mt-5 text-center">
              <p className="font-playfair text-lg text-ivory">{lightbox.guestName}</p>
              {lightbox.caption ? (
                <p className="mt-1 font-cormorant text-base italic text-ivory-soft/70">
                  «{lightbox.caption}»
                </p>
              ) : null}
              <p className="mt-2 font-cormorant text-xs text-gold/60">
                {new Date(lightbox.createdAt).toLocaleDateString("ru-RU", {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
              </p>
            </figcaption>
          </figure>
        </div>
      )}
    </section>
  );
}

function PhotoTile({
  photo,
  onOpen,
}: {
  photo: Photo;
  onOpen: () => void;
}) {
  return (
    <figure
      className="group relative cursor-pointer overflow-hidden rounded-sm border border-gold/15 bg-night"
      onClick={onOpen}
    >
      <div className="relative aspect-square w-full overflow-hidden">
        <img
          src={photo.image}
          alt={photo.caption ?? `Фото от ${photo.guestName}`}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-night/90 via-transparent to-transparent opacity-70 transition-opacity duration-500 group-hover:opacity-95" />
        <div className="absolute inset-0 ring-1 ring-inset ring-gold/0 transition-all duration-500 group-hover:ring-gold/40" />
      </div>
      <figcaption className="absolute bottom-2 left-2 right-2 flex items-end justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-playfair text-xs text-ivory drop-shadow">
            {photo.guestName}
          </p>
          {photo.caption ? (
            <p className="truncate font-cormorant text-[0.7rem] text-ivory-soft/70">
              {photo.caption}
            </p>
          ) : null}
        </div>
        <Heart className="h-3 w-3 shrink-0 text-gold/60" />
      </figcaption>
      <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 scale-50 rounded-full border border-gold/60 bg-night/50 px-3 py-1 font-playfair text-[0.6rem] uppercase tracking-luxe text-gold opacity-0 backdrop-blur-sm transition-all duration-500 group-hover:scale-100 group-hover:opacity-100">
        открыть
      </span>
    </figure>
  );
}

function UploadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M5 20h14" />
    </svg>
  );
}

function plural(n: number, forms: [string, string, string]) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return forms[1];
  return forms[2];
}
