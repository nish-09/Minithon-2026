"use client";
import { useSyncExternalStore } from "react";
/* Thin wrapper over the browser's Web Speech API (speech-to-text + text-to-speech).
   Every failure mode maps to a human message; callers always keep a typed fallback. */

type SR = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: any) => void) | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function ctor(): (new () => SR) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const speechRecognitionSupported = () => ctor() !== null;

/** SSR-safe feature detection (server snapshot is `false`, client re-reads after hydration). */
export function useSpeechSupport(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => ctor() !== null,
    () => false,
  );
}
export const speechSynthesisSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

export function speechErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access is blocked. Allow it in your browser, or type instead.";
    case "no-speech":
      return "I didn't hear anything. Tap the mic and try again.";
    case "audio-capture":
      return "No microphone was found. You can type instead.";
    case "network":
      return "Voice recognition needs a connection. You can type instead.";
    case "unsupported":
      return "Voice input isn't supported in this browser. You can type instead.";
    case "aborted":
      return "";
    default:
      return "Voice input failed. You can type instead.";
  }
}

export interface Listener {
  stop: () => void;
}

/** Starts one recognition session. Returns null (and calls onError) when unsupported. */
export function listen(opts: {
  lang?: string;
  onInterim?: (t: string) => void;
  onFinal: (t: string, confidence: number) => void;
  onError: (code: string) => void;
  onEnd: () => void;
}): Listener | null {
  const C = ctor();
  if (!C) {
    opts.onError("unsupported");
    opts.onEnd();
    return null;
  }
  const rec = new C();
  rec.lang = opts.lang ?? "en-IN";
  rec.interimResults = true;
  // continuous, so a short pause mid-sentence doesn't cut the session off; we end it ourselves after SILENCE_MS of quiet
  rec.continuous = true;
  rec.maxAlternatives = 1;
  const chunks: string[] = [];
  let confidenceSum = 0;
  let flushed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const flush = () => {
    clearTimeout(timer);
    if (flushed) return;
    flushed = true;
    const text = chunks.join(" ").trim();
    if (text) opts.onFinal(text, confidenceSum / chunks.length);
    else opts.onInterim?.("");
  };
  const armSilenceTimer = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { flush(); try { rec.stop(); } catch { /* already stopped */ } }, SILENCE_MS);
  };
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) {
        const t = r[0].transcript.trim();
        if (t) { chunks.push(t); confidenceSum += r[0].confidence ?? 1; }
      } else interim += r[0].transcript;
    }
    const heard = [...chunks, interim.trim()].filter(Boolean).join(" ");
    if (interim || heard) opts.onInterim?.(heard);
    armSilenceTimer();
  };
  rec.onerror = (e) => opts.onError(e.error);
  rec.onend = () => {
    flush();
    opts.onEnd();
  };
  try {
    rec.start();
  } catch {
    opts.onError("audio-capture");
    opts.onEnd();
    return null;
  }
  return { stop: () => { clearTimeout(timer); rec.stop(); } };
}

const SILENCE_MS = 2500;

let voiceEnabled = true;
export function setSpeechOutputEnabled(v: boolean) {
  voiceEnabled = v;
  if (!v) cancelSpeech();
}
export const speechOutputEnabled = () => voiceEnabled;

/* Speech progress feed for lip sync. Browsers expose no audio from speechSynthesis, so the character follows the
   text: word-boundary events (when the voice supplies them) re-anchor its position, and between events it advances
   at the speaking rate. */
export type SpeechEvent = { type: "start"; text: string; rate: number } | { type: "boundary"; charIndex: number } | { type: "end" };
const speechListeners = new Set<(e: SpeechEvent) => void>();
export function subscribeSpeech(fn: (e: SpeechEvent) => void): () => void {
  speechListeners.add(fn);
  return () => { speechListeners.delete(fn); };
}
const emitSpeech = (e: SpeechEvent) => speechListeners.forEach((fn) => fn(e));

export function speak(text: string, opts: { onEnd?: () => void; rate?: number } = {}) {
  if (!voiceEnabled || !speechSynthesisSupported() || !text) {
    opts.onEnd?.();
    return;
  }
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = opts.rate ?? 0.95;
    u.lang = "en-IN";
    u.onstart = () => emitSpeech({ type: "start", text, rate: u.rate });
    u.onboundary = (e) => emitSpeech({ type: "boundary", charIndex: e.charIndex });
    u.onend = () => { emitSpeech({ type: "end" }); opts.onEnd?.(); };
    u.onerror = () => { emitSpeech({ type: "end" }); opts.onEnd?.(); };
    window.speechSynthesis.speak(u);
  } catch {
    opts.onEnd?.();
  }
}

export function cancelSpeech() {
  if (speechSynthesisSupported()) window.speechSynthesis.cancel();
  emitSpeech({ type: "end" });
}

/** Always-on recognition used only for the "Hey NEXA" wake phrase. Restarts itself until stop() is called. */
export function listenForWake(opts: { onTranscript: (t: string) => void; onFatal: (code: string) => void; lang?: string }): Listener | null {
  const C = ctor();
  if (!C) return null;
  let stopped = false;
  let rec: SR | null = null;
  const start = () => {
    if (stopped) return;
    rec = new C();
    rec.lang = opts.lang ?? "en-IN";
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) opts.onTranscript(e.results[i][0].transcript);
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") { stopped = true; opts.onFatal(e.error); }
    };
    rec.onend = () => { if (!stopped) setTimeout(start, 400); };
    try { rec.start(); } catch { setTimeout(start, 1000); }
  };
  start();
  return { stop: () => { stopped = true; try { rec?.abort(); } catch { /* already stopped */ } } };
}
