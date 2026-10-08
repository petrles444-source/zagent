import { cn } from "@/lib/utils";

/** Minimalist heart outline — the recurring symbol from the original invitation. */
export function Heart({
  className,
  filled = false,
}: {
  className?: string;
  filled?: boolean;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("h-4 w-4", className)}
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 20.5C12 20.5 3.5 15.5 3.5 9.2C3.5 6.3 5.8 4 8.6 4C10.3 4 11.6 4.9 12 6.1C12.4 4.9 13.7 4 15.4 4C18.2 4 20.5 6.3 20.5 9.2C20.5 15.5 12 20.5 12 20.5Z" />
    </svg>
  );
}

/** A divider flanked by hairlines + a centered heart, echoing the invitation. */
export function HeartDivider({ className }: { className?: string }) {
  return (
    <div className={cn("ornament-line text-gold", className)} aria-hidden="true">
      <Heart className="h-3.5 w-3.5 text-gold" />
    </div>
  );
}

/** A floral sprig ornament for section corners. */
export function Sprig({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={cn("h-10 w-10 text-gold", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M32 60 V20" />
      <path d="M32 30 C20 28 14 22 16 12 C26 14 32 20 32 30" />
      <path d="M32 24 C44 22 50 16 48 6 C38 8 32 14 32 24" />
      <path d="M32 44 C24 42 20 37 21 30 C28 31 32 36 32 44" />
      <path d="M32 38 C40 36 44 31 43 24 C36 25 32 30 32 38" />
      <circle cx="32" cy="14" r="2.4" />
    </svg>
  );
}

/** Corner flourish for cards / frames. */
export function CornerFlourish({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 80 80"
      className={cn("h-12 w-12 text-gold/70", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M4 4 H30" />
      <path d="M4 4 V30" />
      <path d="M4 30 C 16 28 28 16 30 4" />
      <circle cx="4" cy="4" r="1.6" fill="currentColor" />
    </svg>
  );
}

/** Monogram combining two initials inside a thin double ring. */
export function Monogram({
  left,
  right,
  className,
}: {
  left: string;
  right: string;
  className?: string;
}) {
  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg viewBox="0 0 120 120" className="h-full w-full" aria-hidden="true">
        <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.7" />
        <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="0.5" opacity="0.4" />
      </svg>
      <span className="absolute font-playfair text-gold-gradient text-2xl tracking-wide-2">
        {left}
        <span className="mx-0.5 text-gold/60">&</span>
        {right}
      </span>
    </div>
  );
}

/** Section heading with eyebrow, title and optional divider. */
export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = "center",
  className,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  align?: "center" | "left";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4",
        align === "center" ? "items-center text-center" : "items-start text-left",
        className
      )}
    >
      {eyebrow ? (
        <span className="font-playfair text-[0.7rem] uppercase tracking-luxe text-gold">
          {eyebrow}
        </span>
      ) : null}
      <h2 className="font-playfair text-4xl sm:text-5xl md:text-6xl text-ivory text-balance leading-[1.05]">
        {title}
      </h2>
      <HeartDivider className="w-56" />
      {subtitle ? (
        <p
          className={cn(
            "font-cormorant text-lg sm:text-xl text-ivory-soft/80 leading-relaxed text-balance",
            align === "center" ? "max-w-2xl" : "max-w-xl"
          )}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  );
}
