"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@/lib/hooks";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/hooks";
import { useLiveEvents, useRealtime } from "@/lib/realtime";
import type { IncidentState } from "@/lib/types";
import { Avatar, ErrorState, Spinner, cx } from "./ui";
import { VoicePanel } from "./VoicePanel";
import { VoiceCtx } from "./voice-context";

const NAV = [
  { href: "/", label: "Home", icon: "🏠" },
  { href: "/request/new", label: "Ask for help", icon: "✍️" },
  { href: "/radar", label: "Radar", icon: "🗺️" },
  { href: "/circle", label: "Trusted Circle", icon: "🫂" },
  { href: "/directory", label: "Directory", icon: "📒" },
  { href: "/profile", label: "Profile", icon: "👤" },
];

const EMERGENCY_KINDS = new Set(["emergency_advice", "critical_incident", "incident_escalated"]);

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout, connectionError, refresh } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const toast = useToast();
  const { connected } = useRealtime();
  const unreadQ = useQuery(user ? () => api<{ unread: number }>("/api/notifications?limit=1") : null, [user?.id]);
  const incidentQ = useQuery(user ? () => api<{ incident: IncidentState | null }>("/api/incidents/active") : null, [user?.id]);
  const unread = unreadQ.data?.unread ?? 0;
  const incident = incidentQ.data?.incident ?? null;
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [voiceText, setVoiceText] = useState<string | undefined>(undefined);
  const openVoice = useCallback((t?: string) => {
    setVoiceText(t);
    setVoiceOpen(true);
  }, []);

  useEffect(() => {
    if (!loading && !user && !connectionError) router.replace("/login");
  }, [loading, user, connectionError, router]);

  useLiveEvents((e) => {
    if (e.type === "notification") {
      void unreadQ.reload();
      toast.push({ kind: EMERGENCY_KINDS.has(e.kind) ? "emergency" : "info", title: e.title, body: e.body });
    }
    if (e.type === "incident_update") void incidentQ.reload();
    if (e.type === "message") toast.push({ kind: "info", title: `${e.from}: ${e.body}` });
  });

  if (!user && !loading && connectionError) {
    return (
      <div className="grid min-h-screen place-items-center p-6">
        <div className="max-w-md">
          <ErrorState message={`${connectionError} Your session is safe; we'll reconnect as soon as NEXA is reachable.`} onRetry={() => void refresh().catch(() => undefined)} />
          <p className="mt-4 text-center text-sm text-muted">If this is an emergency, call your local emergency number (112).</p>
        </div>
      </div>
    );
  }
  if (loading || !user) {
    return (
      <div className="grid min-h-screen place-items-center text-muted">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }
  const inCare = path.startsWith("/care");
  const nav = user.role === "admin" ? [...NAV, { href: "/admin", label: "Admin", icon: "🛡️" }] : NAV;
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <VoiceCtx.Provider value={{ open: openVoice }}>
    <div className={cx("min-h-screen bg-bg text-ink lg:grid lg:grid-cols-[250px_1fr]", inCare && "emergency")}>
      <a href="#main" className="sr-only-focusable fixed left-2 top-2 z-[3000] rounded-lg bg-brand px-3 py-2 text-brandink">
        Skip to content
      </a>
      {/* desktop sidebar */}
      <aside className="hidden border-r border-line bg-surface lg:flex lg:flex-col lg:p-5" aria-label="Primary">
        <Link href="/" className="mb-1 text-2xl font-extrabold tracking-tight text-brandtext">
          NEXA
        </Link>
        <p className="mb-6 text-xs text-muted">Your neighborhood, when you need it most.</p>
        <nav className="flex-1 space-y-1">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined} className={cx("flex min-h-11 items-center gap-3 rounded-xl px-3 font-medium transition", active(n.href) ? "bg-brandsoft text-brandtext" : "hover:bg-surface2")}>
              <span aria-hidden>{n.icon}</span>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="mt-4 flex items-center gap-3 border-t border-line pt-4">
          <Avatar name={user.name} src={user.avatar_url} size={36} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{user.name}</p>
            <button onClick={() => void logout().then(() => router.replace("/login"))} className="text-xs text-muted underline">
              Log out
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col pb-24 lg:pb-0">
        <header className="sticky top-0 z-[1000] flex items-center gap-3 border-b border-line bg-bg/85 px-4 py-2.5 backdrop-blur">
          <Link href="/" className="text-xl font-extrabold tracking-tight text-brandtext lg:hidden">
            NEXA
          </Link>
          <span className={cx("hidden items-center gap-1.5 text-xs sm:flex", connected ? "text-ok" : "text-muted")} title={connected ? "Live updates connected" : "Reconnecting to live updates…"}>
            <span className={cx("h-2 w-2 rounded-full", connected ? "bg-oksolid" : "bg-warn")} /> {connected ? "Live" : "Reconnecting…"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => openVoice()} className="flex h-11 min-w-11 items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-brandsoft px-3 text-brandtext" aria-label="Talk to NEXA">
              🎙 <span className="ml-1.5 hidden text-sm font-semibold sm:inline">Talk to NEXA</span>
            </button>
            <Link href="/notifications" className="relative grid h-11 w-11 place-items-center rounded-full hover:bg-surface2" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
              🔔
              {unread > 0 && <span className="absolute right-1 top-1 grid h-5 min-w-5 place-items-center rounded-full bg-dangersolid px-1 text-[11px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
            </Link>
            <Link href="/care" className="grid h-11 place-items-center rounded-full bg-dangersolid px-4 text-sm font-bold text-white shadow" aria-label="Emergency help: start NEXA CARE">
              SOS
            </Link>
          </div>
        </header>

        {incident && !inCare && (
          <Link href={`/care/${incident.id}`} className="flex items-center justify-between gap-3 bg-dangersolid px-4 py-3 text-white" role="alert">
            <span className="font-semibold">● NEXA CARE is active ({incident.incident_id})</span>
            <span className="text-sm underline">Return to care →</span>
          </Link>
        )}

        <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-5 sm:px-6">
          {children}
        </main>
      </div>

      {/* mobile tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-[1000] grid grid-cols-5 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Primary">
        {[NAV[0], NAV[1], NAV[2], NAV[3], NAV[5]].map((n) => (
          <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined} className={cx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium", active(n.href) ? "text-brandtext" : "text-muted")}>
            <span className="text-lg" aria-hidden>
              {n.icon}
            </span>
            {n.label === "Trusted Circle" ? "Circle" : n.label === "Ask for help" ? "Ask" : n.label}
          </Link>
        ))}
      </nav>
      <VoicePanel open={voiceOpen} onClose={() => setVoiceOpen(false)} initialText={voiceText} />
    </div>
    </VoiceCtx.Provider>
  );
}
