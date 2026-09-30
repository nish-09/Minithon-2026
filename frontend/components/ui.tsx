"use client";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { initials } from "@/lib/format";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/* ---------- buttons ---------- */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand text-brandink hover:brightness-110 shadow-sm",
  secondary: "bg-surface2 text-ink hover:brightness-95 border border-line",
  ghost: "text-ink hover:bg-surface2",
  danger: "bg-dangersolid text-white hover:brightness-110",
  success: "bg-oksolid text-white hover:brightness-110",
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "min-h-9 px-3 text-sm" : size === "lg" ? "min-h-14 px-6 text-lg" : "px-4 text-[15px]",
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
export function Card({ children, className, as: Tag = "section", ...rest }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" } & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag {...rest} className={cx("rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5", className)}>
      {children}
    </Tag>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-base font-semibold tracking-tight">{children}</h2>
      {action}
    </div>
  );
}

type Tone = "neutral" | "brand" | "ok" | "warn" | "danger";
const TONE: Record<Tone, string> = {
  neutral: "bg-surface2 text-muted",
  brand: "bg-brandsoft text-brandtext",
  ok: "bg-oksoft text-ok",
  warn: "bg-warnsoft text-warn",
  danger: "bg-dangersoft text-danger",
};
export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", TONE[tone], className)}>{children}</span>;
}

export function UrgencyBadge({ urgency }: { urgency: string }) {
  return urgency === "critical" ? <Badge tone="danger">● Critical</Badge> : urgency === "urgent" ? <Badge tone="warn">Urgent</Badge> : <Badge>Normal</Badge>;
}

export function Avatar({ name, src, size = 40 }: { name: string; src?: string | null; size?: number }) {
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} className="rounded-full object-cover" style={{ width: size, height: size }} />
  ) : (
    <span aria-hidden className="grid shrink-0 place-items-center rounded-full bg-brandsoft font-semibold text-brandtext" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      {initials(name)}
    </span>
  );
}

/* ---------- states ---------- */
export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-muted" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-2xl border border-danger/30 bg-dangersoft p-5 text-center">
      <p className="font-semibold">Something didn&apos;t load</p>
      <p className="mt-1 text-sm text-muted">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ icon = "🌿", title, body, action }: { icon?: string; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line p-8 text-center">
      <div className="text-3xl" aria-hidden>
        {icon}
      </div>
      <p className="mt-2 font-semibold">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-sm text-sm text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "warn", children, className }: { tone?: "warn" | "danger" | "ok" | "brand"; children: ReactNode; className?: string }) {
  const t = { warn: "bg-warnsoft", danger: "bg-dangersoft", ok: "bg-oksoft", brand: "bg-brandsoft" }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "note"} className={cx("rounded-xl px-4 py-3 text-sm", t, className)}>
      {children}
    </div>
  );
}

/* ---------- form controls ---------- */
export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      {children(id)}
      {hint && !error && <p className="mt-1 text-xs text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

const INPUT = "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[15px] placeholder:text-muted/70 focus:border-brand";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(INPUT, p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(INPUT, "resize-y", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(INPUT, "pr-8", p.className)} />;

export function Toggle({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-medium">
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
        className={cx("relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50", checked ? "bg-brand" : "bg-line")}
      >
        <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all", checked ? "left-[22px]" : "left-0.5")} />
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
    <div className="fixed inset-0 z-[1500] grid items-end bg-black/50 p-0 sm:place-items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={cx("rise max-h-[92vh] w-full overflow-y-auto rounded-t-3xl bg-surface p-5 shadow-2xl sm:rounded-3xl", wide ? "sm:max-w-2xl" : "sm:max-w-md")}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full hover:bg-surface2">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ProgressBar({ value, tone = "brand", label }: { value: number; tone?: "brand" | "ok" | "warn" | "danger"; label?: string }) {
  const bg = { brand: "bg-brand", ok: "bg-oksolid", warn: "bg-warn", danger: "bg-dangersolid" }[tone];
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface2" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className={cx("h-full rounded-full transition-all", bg)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl border border-line bg-surface2 p-1">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} className={cx("min-h-9 rounded-lg px-3 text-sm font-medium transition", value === o.value ? "bg-surface shadow-sm" : "text-muted")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
