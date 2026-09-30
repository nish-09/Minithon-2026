"use client";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { WS_URL, getToken } from "./api";
import { useAuth } from "./auth";

export interface LiveEvent {
  type: "hello" | "pong" | "notification" | "request_update" | "incident_update" | "message";
  [k: string]: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
type Handler = (e: LiveEvent) => void;

interface Ctx {
  connected: boolean;
  subscribe: (h: Handler) => () => void;
}
const RealtimeCtx = createContext<Ctx>({ connected: false, subscribe: () => () => {} });

/** One WebSocket per session with exponential-backoff reconnect and a heartbeat. */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const handlers = useRef(new Set<Handler>());
  const [connected, setConnected] = useState(false);
  const userId = user?.id;

  useEffect(() => {
    if (!userId) return;
    let ws: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let beat: ReturnType<typeof setInterval> | undefined;

    const open = () => {
      const token = getToken();
      if (!token || stopped) return;
      ws = new WebSocket(`${WS_URL}/ws?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        beat = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
      };
      ws.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data) as LiveEvent;
          handlers.current.forEach((h) => h(ev));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = (ev) => {
        setConnected(false);
        if (beat) clearInterval(beat);
        if (stopped || ev.code === 4401) return; // 4401: bad/revoked token, do not hammer the server
        attempt += 1;
        retry = setTimeout(open, Math.min(30000, 1000 * 2 ** Math.min(attempt, 5)));
      };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      if (beat) clearInterval(beat);
      ws?.close();
      setConnected(false);
    };
  }, [userId]);

  const value = useMemo<Ctx>(
    () => ({
      connected,
      subscribe: (h) => {
        handlers.current.add(h);
        return () => handlers.current.delete(h);
      },
    }),
    [connected],
  );
  return <RealtimeCtx.Provider value={value}>{children}</RealtimeCtx.Provider>;
}

export function useRealtime() {
  return useContext(RealtimeCtx);
}

/** Runs `onEvent` for matching live events; call the returned-from-hook refetch from inside. */
export function useLiveEvents(onEvent: Handler, deps: unknown[] = []) {
  const { subscribe } = useRealtime();
  const ref = useRef(onEvent);
  useEffect(() => {
    ref.current = onEvent;
  });
  const key = JSON.stringify(deps);
  useEffect(() => subscribe((e) => ref.current(e)), [subscribe, key]);
}
