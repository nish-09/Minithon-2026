"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, errorMessage } from "./api";
import { useAuth } from "./auth";

/* ---------- data fetching ---------- */
/** Fetch-on-mount/deps query. `loading` is only true for the first load of a given key; `reload()` refreshes silently. */
export function useQuery<T>(fn: (() => Promise<T>) | null, deps: unknown[] = []) {
  const key = JSON.stringify([fn === null, ...deps]);
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key: "", data: null, error: null });
  const fnRef = useRef(fn);
  const keyRef = useRef(key);
  const seq = useRef(0);
  useEffect(() => {
    fnRef.current = fn;
    keyRef.current = key;
  });

  const reload = useCallback(async () => {
    const f = fnRef.current;
    if (!f) return;
    const my = ++seq.current;
    const k = keyRef.current;
    try {
      const d = await f();
      if (my === seq.current) setState({ key: k, data: d, error: null });
    } catch (e) {
      if (my === seq.current) setState((s) => ({ key: k, data: s.key === k ? s.data : null, error: errorMessage(e) }));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [key, reload]);

  const fresh = state.key === key;
  const setData = useCallback((u: T | null | ((p: T | null) => T | null)) => setState((s) => ({ ...s, data: typeof u === "function" ? (u as (p: T | null) => T | null)(s.data) : u })), []);
  return { data: fresh ? state.data : null, error: fresh ? state.error : null, loading: fn !== null && !fresh, reload, setData };
}

/* ---------- toasts ---------- */
interface Toast {
  id: number;
  kind: "info" | "success" | "error" | "emergency";
  title: string;
  body?: string;
}
const ToastCtx = createContext<{ push: (t: Omit<Toast, "id">) => void }>({ push: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = next.current++;
    setItems((x) => [...x.slice(-3), { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.kind === "error" ? 7000 : 5000);
  }, []);
  const value = useMemo(() => ({ push }), [push]);
  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 top-3 z-[2000] mx-auto flex w-full max-w-md flex-col gap-2 px-3">
        {items.map((t) => (
          <div
            key={t.id}
            className={`rise clay-card pointer-events-auto flex gap-3 border-2 px-4 py-3 ${
              t.kind === "error" || t.kind === "emergency" ? "!border-danger" : t.kind === "success" ? "!border-ok" : "!border-brand"
            }`}
          >
            <span aria-hidden className="font-extrabold">{t.kind === "error" ? "⚠" : t.kind === "emergency" ? "⬢" : t.kind === "success" ? "✓" : "ℹ"}</span>
            <div>
              <p className="text-sm font-bold">{t.kind === "error" ? "Problem: " : t.kind === "emergency" ? "Emergency: " : t.kind === "success" ? "Done: " : ""}{t.title}</p>
              {t.body && <p className="mt-0.5 text-sm">{t.body}</p>}
            </div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---------- geolocation ---------- */
export const SAMPLE_LOCATION = { lat: 19.0645, lng: 72.8358, label: "TSEC Bandra West, Mumbai (sample)" };

export type GeoStatus = "idle" | "asking" | "granted" | "denied" | "unavailable" | "error";

/** Device position with explicit permission states. On success the position is stored on the profile
    (so nearby matching works) unless the user turned location sharing off. */
export function useLocation() {
  const { user, refresh } = useAuth();
  const [status, setStatus] = useState<GeoStatus>("idle");
  const [override, setOverride] = useState<{ lat: number; lng: number } | null>(null);
  const toast = useToast();
  const coords = override ?? (user?.lat != null && user?.lng != null ? { lat: user.lat, lng: user.lng } : null);

  const save = useCallback(
    async (lat: number, lng: number) => {
      setOverride({ lat, lng });
      try {
        await api("/api/users/me/location", { method: "PUT", body: { lat, lng } });
        await refresh();
      } catch (e) {
        toast.push({ kind: "error", title: "Couldn't save your location", body: errorMessage(e) });
      }
    },
    [refresh, toast],
  );

  const request = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setStatus("unavailable");
      return;
    }
    setStatus("asking");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setStatus("granted");
        void save(p.coords.latitude, p.coords.longitude);
      },
      (err) => setStatus(err.code === err.PERMISSION_DENIED ? "denied" : "error"),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }, [save]);

  const useSample = useCallback(() => {
    setStatus("granted");
    return save(SAMPLE_LOCATION.lat, SAMPLE_LOCATION.lng);
  }, [save]);

  return { coords, status, request, useSample, setManual: save };
}
