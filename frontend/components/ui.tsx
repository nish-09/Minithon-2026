"use client";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertTriangle, Info, OctagonAlert, Sprout, TriangleAlert, CheckCircle2 } from "lucide-react";
import { initials } from "@/lib/format";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/* ---------- buttons (raised clay, pressed = inset) ---------- */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "highlight" | "info" | "emergency" | "emergency-secondary";
const VARIANT: Record<Variant, string> = {
  primary: "clay-btn bg-lavender",
  highlight: "clay-btn bg-yellow",
  info: "clay-btn bg-sky",
  secondary: "clay-btn clay-btn-secondary",
  ghost: "rounded-2xl font-semibold text-ink transition-colors duration-150 hover:bg-white/60",
  danger: "clay-btn bg-dangersolid text-white",
  success: "clay-btn bg-mint",
  emergency: "emergency-btn",
  "emergency-secondary": "emergency-btn-secondary",
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" | "xl"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "min-h-11 px-4 text-sm" : size === "lg" ? "min-h-14 px-6 text-lg" : size === "xl" ? "min-h-16 px-7 text-xl" : "min-h-12 px-5 text-[15px]",
        VARIANT[variant],
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className ?? "h-5 w-5")} viewBox="0 0 24 24" fill="none" role="img" aria-label="Loading">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity=".25" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- surfaces ---------- */
export type CardTone = "neutral" | "yellow" | "lavender" | "mint" | "peach" | "sky";
/** Neutral clay by default; pastel tones are accents and should stay a minority of the cards on a page. */
export function Card({ children, className, tone = "neutral", as: Tag = "section", ...rest }: { children: ReactNode; className?: string; tone?: CardTone; as?: "section" | "div" | "article" } & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag {...rest} className={cx("clay-card p-5 sm:p-6", tone !== "neutral" && `tone-${tone}`, className)}>
      {children}
    </Tag>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-lg font-bold tracking-tight">{children}</h2>
      {action}
    </div>
  );
}

/* ---------- badges: state is ALWAYS icon + text (+ colour), never colour alone ---------- */
type Tone = "neutral" | "brand" | "ok" | "warn" | "danger" | "info";
const TONE: Record<Tone, string> = {
  neutral: "bg-surface2 border-linestrong",
  brand: "bg-lavender border-ink/30",
  ok: "bg-mint border-ink/30",
  warn: "bg-yellow border-ink/30",
  danger: "bg-peach border-ink/30",
  info: "bg-sky border-ink/30",
};
export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: string; children: ReactNode; className?: string }) {
  return (
    <span className={cx("clay-pill inline-flex items-center gap-1.5 border px-3 py-1 text-xs font-bold text-ink", TONE[tone], className)}>
      {icon && <span aria-hidden>{icon}</span>}
      {children}
    </span>
  );
}

/** Priority: NORMAL (calm), URGENT (warning), CRITICAL (emergency). Distinct glyph + word + colour. */
export function UrgencyBadge({ urgency }: { urgency: string }) {
  if (urgency === "critical") return <Badge tone="danger" icon="⬢">CRITICAL</Badge>;
  if (urgency === "urgent") return <Badge tone="warn" icon="▲">URGENT</Badge>;
  return <Badge tone="neutral" icon="●">Normal</Badge>;
}

const STATUS: Record<string, { icon: string; tone: Tone; label: string }> = {
  CREATED: { icon: "●", tone: "neutral", label: "Created" },
  ANALYZING: { icon: "◌", tone: "info", label: "Understanding" },
  MATCHING: { icon: "◌", tone: "info", label: "Finding help" },
  TRUSTED_CIRCLE: { icon: "♥", tone: "brand", label: "Asking Trusted Circle" },
  HELPERS_NOTIFIED: { icon: "◌", tone: "info", label: "Helpers notified" },
  ESCALATED: { icon: "↗", tone: "warn", label: "Widening to community" },
  ASSIGNED: { icon: "✓", tone: "ok", label: "Helper assigned" },
  ACCEPTED: { icon: "✓", tone: "ok", label: "Helper accepted" },
  ON_THE_WAY: { icon: "➜", tone: "ok", label: "Helper on the way" },
  IN_PROGRESS: { icon: "✚", tone: "ok", label: "Help in progress" },
  COMPLETED: { icon: "✓", tone: "ok", label: "COMPLETED" },
  RATED: { icon: "★", tone: "ok", label: "Completed & rated" },
  CANCELLED: { icon: "✕", tone: "neutral", label: "Cancelled" },
  EXPIRED: { icon: "⌛", tone: "warn", label: "Expired" },
};
export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { icon: "●", tone: "neutral" as Tone, label: status };
  return <Badge tone={s.tone} icon={s.icon}>{s.label}</Badge>;
}

export function AvailabilityBadge({ available }: { available: boolean | null | undefined }) {
  return available ? <Badge tone="ok" icon="●">Available</Badge> : <Badge tone="neutral" icon="○">Not available</Badge>;
}

export function VerifiedBadge({ verified, label = "Identity" }: { verified: boolean; label?: string }) {
  return verified ? <Badge tone="ok" icon="✓">{label} verified</Badge> : <Badge tone="warn" icon="!">{label} not verified</Badge>;
}

export function Avatar({ name, src, size = 40 }: { name: string; src?: string | null; size?: number }) {
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} className="rounded-full border-2 border-white object-cover shadow" style={{ width: size, height: size }} />
  ) : (
    <span aria-hidden className="grid shrink-0 place-items-center rounded-full border-2 border-white bg-lavender font-bold text-ink shadow" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      {initials(name)}
    </span>
  );
}

/* ---------- states ---------- */
export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="space-y-3 py-4" aria-busy="true">
      <span className="sr-only">{label}</span>
      <div className="skeleton h-6 w-2/5" />
      <div className="skeleton h-20 w-full" />
      <div className="skeleton h-20 w-full" />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="clay-card border-2 !border-danger p-5 text-center">
      <p className="flex items-center justify-center gap-2 font-bold text-danger"><TriangleAlert aria-hidden size={20} />Something didn&apos;t load</p>
      <p className="mt-1 text-sm">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="clay-well p-8 text-center">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-mint text-ink shadow" aria-hidden>
        {icon ?? <Sprout size={26} />}
      </div>
      <p className="mt-2 font-bold">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-sm text-sm text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const NOTICE: Record<string, { cls: string; Icon: typeof Info; word: string }> = {
  warn: { cls: "bg-yellow", Icon: TriangleAlert, word: "Note" },
  danger: { cls: "bg-peach", Icon: OctagonAlert, word: "Problem" },
  ok: { cls: "bg-mint", Icon: CheckCircle2, word: "Success" },
  brand: { cls: "bg-sky", Icon: Info, word: "Info" },
};
export function Notice({ tone = "warn", children, className }: { tone?: "warn" | "danger" | "ok" | "brand"; children: ReactNode; className?: string }) {
  const n = NOTICE[tone];
  return (
    <div role={tone === "danger" ? "alert" : "note"} className={cx("clay-card flex gap-3 !rounded-2xl px-4 py-3 text-sm text-ink", n.cls, className)}>
      <n.Icon aria-hidden size={20} className="mt-0.5 shrink-0" />
      <span className="sr-only">{n.word}:</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/* ---------- form controls ---------- */
export interface FieldA11y {
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  "aria-required"?: boolean;
}

/** Visible label, explicit "(required)", and an error that is text + icon (never just a red border). */
export function Field({ label, hint, error, required, children }: { label: string; hint?: string; error?: string | null; required?: boolean; children: (id: string, a: FieldA11y) => ReactNode }) {
  const id = useId();
  const msgId = `${id}-msg`;
  const a: FieldA11y = { "aria-describedby": error || hint ? msgId : undefined, "aria-invalid": error ? true : undefined, "aria-required": required || undefined };
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-bold">
        {label}
        {required && <span className="font-semibold text-muted"> (required)</span>}
      </label>
      {children(id, a)}
      {error ? (
        <p id={msgId} role="alert" className="mt-1.5 flex gap-1.5 text-sm font-bold text-danger">
          <AlertTriangle aria-hidden size={16} className="mt-0.5 shrink-0" />
          {error}
        </p>
      ) : hint ? (
        <p id={msgId} className="mt-1 text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

const INPUT = "clay-input min-h-12 w-full px-4 py-2.5 text-[15px] text-ink placeholder:text-muted";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(INPUT, p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(INPUT, "resize-y", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(INPUT, "pr-8", p.className)} />;

export function Toggle({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-bold">
          {label}
        </label>
        {description && <p className="text-xs text-muted">{description}</p>}
      </div>
      <button
        id={id}
        role="switch"
        type="button"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="flex min-h-11 shrink-0 items-center gap-2 disabled:opacity-60"
      >
        <span className="w-7 text-right text-xs font-extrabold" aria-hidden>{checked ? "On" : "Off"}</span>
        <span className={cx("relative h-8 w-14 rounded-full border-2 transition-colors", checked ? "border-[#4a2fb0] bg-lavender" : "border-linestrong bg-surface2")} style={{ boxShadow: "var(--clay-recess)" }}>
          <span className={cx("absolute top-0.5 h-6 w-6 rounded-full border-2 bg-white transition-all", checked ? "left-[26px] border-[#4a2fb0]" : "left-0.5 border-linestrong")} style={{ boxShadow: "var(--clay-out-sm)" }} />
        </span>
      </button>
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[1500] grid items-end bg-[#172033]/55 p-0 sm:place-items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={cx("rise clay-card max-h-[92vh] w-full overflow-y-auto !rounded-b-none !rounded-t-[28px] p-6 sm:!rounded-[28px]", wide ? "sm:max-w-2xl" : "sm:max-w-md")}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-xl font-bold">{title}</h2>
          <button onClick={onClose} aria-label={`Close ${title}`} className="clay-btn clay-btn-secondary grid h-11 w-11 place-items-center !rounded-full">
            <span aria-hidden>✕</span>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ProgressBar({ value, tone = "brand", label }: { value: number; tone?: "brand" | "ok" | "warn" | "danger"; label?: string }) {
  const bg = { brand: "bg-lavender", ok: "bg-mint", warn: "bg-yellow", danger: "bg-peach" }[tone];
  return (
    <div className="clay-well h-3 w-full overflow-hidden !rounded-full" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className={cx("h-full rounded-full transition-all", bg)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="clay-well inline-flex flex-wrap gap-1 p-1">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} className={cx("min-h-11 rounded-2xl px-3.5 text-sm font-bold transition", value === o.value ? "clay-btn bg-lavender" : "text-ink transition-colors duration-150 hover:bg-white/70")}>
          <span aria-hidden>{value === o.value ? "✓ " : ""}</span>
          {o.label}
        </button>
      ))}
    </div>
  );
}
