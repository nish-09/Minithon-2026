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
  rec.continuous = false;
  rec.maxAlternatives = 1;
  let gotFinal = false;
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) {
        gotFinal = true;
        opts.onFinal(r[0].transcript.trim(), r[0].confidence ?? 1);
      } else interim += r[0].transcript;
    }
    if (interim) opts.onInterim?.(interim);
  };
  rec.onerror = (e) => opts.onError(e.error);
  rec.onend = () => {
    if (!gotFinal) opts.onInterim?.("");
    opts.onEnd();
  };
  try {
    rec.start();
  } catch {
    opts.onError("audio-capture");
    opts.onEnd();
    return null;
  }
  return { stop: () => rec.stop() };
}

let voiceEnabled = true;
export function setSpeechOutputEnabled(v: boolean) {
  voiceEnabled = v;
  if (!v) cancelSpeech();
}
export const speechOutputEnabled = () => voiceEnabled;

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
    u.onend = () => opts.onEnd?.();
    u.onerror = () => opts.onEnd?.();
    window.speechSynthesis.speak(u);
  } catch {
    opts.onEnd?.();
  }
}

export function cancelSpeech() {
  if (speechSynthesisSupported()) window.speechSynthesis.cancel();
}
