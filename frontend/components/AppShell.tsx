"use client";
import { Bell, BookOpen, Home, LogOut, Map as MapIcon, Menu, PanelLeftClose, PanelLeftOpen, PenLine, ShieldCheck, UserRound, Users, X } from "lucide-react";
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
import { NexaMode } from "./NexaMode";
import NexaFab from "./NexaFab";
import { VoiceCtx } from "./voice-context";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/request/new", label: "Ask for help", icon: PenLine },
  { href: "/radar", label: "Radar", icon: MapIcon },
  { href: "/circle", label: "Trusted Circle", icon: Users },
  { href: "/directory", label: "Directory", icon: BookOpen },
  { href: "/profile", label: "Profile", icon: UserRound },
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
  const [collapsed, setCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // Restore sidebar collapsed preference
  useEffect(() => {
    try {
      const saved = localStorage.getItem("nexa_sidebar_collapsed");
      if (saved !== null) {
        setCollapsed(saved === "true");
      }
    } catch {
      // LocalStorage access safe fallback
    }
  }, []);

  const toggleCollapse = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("nexa_sidebar_collapsed", String(next));
      } catch {}
      return next;
    });
  }, []);

  // Keyboard shortcut Ctrl+B / Cmd+B to toggle sidebar collapse; Escape to close mobile drawer
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleCollapse();
      }
      if (e.key === "Escape") {
        setMobileDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleCollapse]);

  // Close mobile drawer on route navigation
  useEffect(() => {
    setMobileDrawerOpen(false);
  }, [path]);

  const openVoice = useCallback((t?: string) => {
    setVoiceText(t);
    setVoiceOpen(true);
  }, []);

  useEffect(() => {
    if (!loading && !user && !connectionError) router.replace("/login");
  }, [loading, user, connectionError, router]);

  const [announce, setAnnounce] = useState("");
  useLiveEvents((e) => {
    if (e.type === "notification") {
      setAnnounce(`${e.title}. ${e.body ?? ""}`);
      void unreadQ.reload();
      toast.push({ kind: EMERGENCY_KINDS.has(e.kind) ? "emergency" : "info", title: e.title, body: e.body });
    }
    if (e.type === "incident_update") {
      void incidentQ.reload();
      setAnnounce("NEXA CARE incident updated.");
    }
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
  const nav = user.role === "admin" ? [...NAV, { href: "/admin", label: "Admin", icon: ShieldCheck }] : NAV;
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <VoiceCtx.Provider value={{ open: openVoice }}>
    <div className="min-h-screen text-ink lg:flex">
      <a href="#main" className="sr-only-focusable clay-btn fixed left-2 top-2 z-[3000] bg-brand px-4 py-3 text-brandink">
        Skip to content
      </a>

      {/* desktop sidebar: fixed/sticky so it never scrolls off screen, and fast collapsable */}
      <aside
        className={cx(
          "clay-card hidden lg:sticky lg:top-3 lg:self-start lg:m-3 lg:flex lg:flex-col",
          "lg:h-[calc(100vh-1.5rem)] lg:overflow-hidden z-20 shrink-0 transition-[width,padding] duration-150 ease-out",
          collapsed ? "w-[76px] p-2.5 items-center" : "w-[260px] p-5"
        )}
        aria-label="Primary"
      >
        {/* Brand Header */}
        <div className={cx("shrink-0 w-full mb-3", collapsed ? "flex justify-center pt-1" : "px-1")}>
          {!collapsed ? (
            <div>
              <Link href="/" className="text-2xl font-extrabold tracking-tight text-brandtext hover:opacity-85 transition-opacity block">
                NEXA
              </Link>
              <p className="mt-0.5 text-xs text-muted">Your neighborhood, when you need it most.</p>
            </div>
          ) : (
            <Link
              href="/"
              className="clay-btn bg-lavender grid h-11 w-11 place-items-center !rounded-2xl text-lg font-black text-brandtext shadow-sm hover:scale-105 transition-transform"
              title="NEXA Home"
              aria-label="NEXA Home"
            >
              N
            </Link>
          )}
        </div>

        {/* Navigation list */}
        <nav className={cx("flex-1 space-y-1.5 overflow-y-auto overflow-x-hidden min-h-0 py-1 custom-scrollbar w-full", !collapsed && "mt-2")}>
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active(n.href) ? "page" : undefined}
              title={collapsed ? n.label : undefined}
              aria-label={collapsed ? n.label : undefined}
              className={cx(
                "flex min-h-12 items-center rounded-2xl font-bold transition-colors duration-150",
                collapsed ? "justify-center p-2 mx-auto w-11 h-11" : "gap-3 px-3 w-full",
                active(n.href) ? "clay-btn bg-lavender text-ink" : "border border-transparent text-ink hover:bg-surface/60"
              )}
            >
              <n.icon aria-hidden size={20} className="shrink-0" />
              {!collapsed && <span className="truncate">{n.label}</span>}
            </Link>
          ))}
        </nav>

        {/* User profile footer */}
        <div className={cx("mt-auto border-t-2 border-line pt-3 shrink-0 w-full", collapsed ? "flex flex-col items-center gap-2" : "flex items-center gap-3 px-1")}>
          {!collapsed ? (
            <>
              <div className="shrink-0">
                <Avatar name={user.name} src={user.avatar_url} size={36} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{user.name}</p>
                <button
                  type="button"
                  onClick={() => void logout().then(() => router.replace("/login"))}
                  className="min-h-6 text-sm font-semibold text-brandtext underline hover:opacity-80"
                >
                  Log out
                </button>
              </div>
            </>
          ) : (
            <>
              <div title={user.name}>
                <Avatar name={user.name} src={user.avatar_url} size={34} />
              </div>
              <button
                type="button"
                onClick={() => void logout().then(() => router.replace("/login"))}
                title="Log out"
                aria-label="Log out"
                className="grid h-9 w-9 place-items-center rounded-xl text-muted hover:bg-surface/60 hover:text-brandtext transition-colors"
              >
                <LogOut aria-hidden size={18} />
              </button>
            </>
          )}
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col pb-24 lg:pb-0">
        <header className="clay-card sticky top-3 z-[1000] mx-3 mt-3 flex items-center gap-3 !rounded-[22px] !p-0 px-4 py-2.5">
          {/* Mobile navigation trigger */}
          <button
            type="button"
            onClick={() => setMobileDrawerOpen(true)}
            className="clay-btn clay-btn-secondary grid h-11 w-11 shrink-0 place-items-center !rounded-full text-ink hover:bg-surface/80 active:scale-95 transition-all lg:hidden"
            aria-label="Open navigation menu"
            title="Open navigation menu"
          >
            <Menu aria-hidden size={20} />
          </button>

          {/* Desktop sidebar collapse/expand trigger */}
          <button
            type="button"
            onClick={toggleCollapse}
            className="clay-btn clay-btn-secondary hidden h-11 w-11 shrink-0 place-items-center !rounded-full text-ink hover:bg-surface/80 active:scale-95 transition-all lg:grid"
            aria-label={collapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"}
            title={collapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"}
          >
            {collapsed ? <PanelLeftOpen aria-hidden size={19} /> : <PanelLeftClose aria-hidden size={19} />}
          </button>

          <Link href="/" className="text-xl font-extrabold tracking-tight text-brandtext lg:hidden">
            NEXA
          </Link>
          <span className={cx("hidden items-center gap-1.5 text-xs font-bold sm:flex", connected ? "text-ok" : "text-warn")} title={connected ? "Live updates connected" : "Reconnecting to live updates…"}>
            <span aria-hidden>{connected ? "●" : "▲"}</span> {connected ? "Live updates on" : "Reconnecting…"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/notifications" className="clay-btn clay-btn-secondary relative grid h-11 w-11 place-items-center !rounded-full" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
              <Bell aria-hidden size={20} />
              {unread > 0 && <span className="absolute right-1 top-1 grid h-5 min-w-5 place-items-center rounded-full bg-dangersolid px-1 text-[11px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
            </Link>
            <Link href="/care" className="clay-btn grid h-11 min-w-11 place-items-center !rounded-full bg-dangersolid px-4 text-sm text-white" aria-label="Emergency help: start NEXA CARE">
              SOS
            </Link>
          </div>
        </header>

        {incident && !inCare && (
          <div role="alert" className="mx-3 mt-3"><Link href={`/care/${incident.id}`} className="emergency-strip flex min-h-12 items-center justify-between gap-3 px-4 py-3">
            <span className="font-extrabold">⬢ CRITICAL: NEXA CARE is active ({incident.incident_id})</span>
            <span className="text-sm underline">Return to care →</span>
          </Link></div>
        )}

        <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-5 sm:px-6">
          {children}
        </main>
      </div>

      {/* mobile tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-[1000] grid grid-cols-5 bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_18px_rgb(92_110_140/0.18)] lg:hidden" aria-label="Primary">
        {[NAV[0], NAV[1], NAV[2], NAV[3], NAV[5]].map((n) => (
          <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined} className={cx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-bold", active(n.href) ? "m-1 rounded-2xl bg-lavender text-ink" : "text-muted")}>
            <n.icon aria-hidden size={22} />
            {n.label === "Trusted Circle" ? "Circle" : n.label === "Ask for help" ? "Ask" : n.label}
          </Link>
        ))}
      </nav>

      {/* mobile slide-over drawer */}
      {mobileDrawerOpen && (
        <div className="fixed inset-0 z-[2000] lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation drawer">
          <div
            className="fixed inset-0 bg-ink/40 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="clay-card fixed inset-y-2 left-2 z-[2001] flex w-72 max-w-[85vw] flex-col !rounded-[28px] p-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <Link href="/" onClick={() => setMobileDrawerOpen(false)} className="text-2xl font-extrabold tracking-tight text-brandtext">
                NEXA
              </Link>
              <button
                type="button"
                onClick={() => setMobileDrawerOpen(false)}
                className="clay-btn clay-btn-secondary grid h-9 w-9 place-items-center !rounded-xl text-muted hover:text-ink"
                aria-label="Close navigation menu"
              >
                <X aria-hidden size={18} />
              </button>
            </div>
            <p className="mt-0.5 mb-4 text-xs text-muted">Your neighborhood, when you need it most.</p>

            <nav className="flex-1 space-y-1.5 overflow-y-auto overflow-x-hidden min-h-0 py-2 custom-scrollbar">
              {nav.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  onClick={() => setMobileDrawerOpen(false)}
                  aria-current={active(n.href) ? "page" : undefined}
                  className={cx(
                    "flex min-h-12 items-center gap-3 rounded-2xl px-3 font-bold transition",
                    active(n.href) ? "clay-btn bg-lavender text-ink" : "border border-transparent text-ink transition-colors duration-150 hover:bg-surface/60"
                  )}
                >
                  <n.icon aria-hidden size={20} />
                  {n.label}
                </Link>
              ))}
            </nav>

            <div className="mt-auto border-t-2 border-line pt-4 flex items-center gap-3">
              <Avatar name={user.name} src={user.avatar_url} size={36} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{user.name}</p>
                <button
                  type="button"
                  onClick={() => void logout().then(() => router.replace("/login"))}
                  className="min-h-6 text-sm font-semibold text-brandtext underline"
                >
                  Log out
                </button>
              </div>
            </div>
          </aside>
        </div>
      )}

      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">{announce}</div>
      <NexaFab onOpen={openVoice} hidden={voiceOpen} />
      <NexaMode open={voiceOpen} onClose={() => setVoiceOpen(false)} initialText={voiceText} />
    </div>
    </VoiceCtx.Provider>
  );
}
