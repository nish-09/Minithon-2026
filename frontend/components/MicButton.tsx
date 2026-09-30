"use client";
import { useEffect, useRef, useState } from "react";
import { listen, speechErrorMessage, useSpeechSupport, type Listener } from "@/lib/speech";
import { cx } from "./ui";

/** Dictation button: puts the recognised text into a field. Shows its own errors and never blocks typing. */
export function MicButton({ onTranscript, onInterim, className }: { onTranscript: (text: string) => void; onInterim?: (t: string) => void; className?: string }) {
  const [on, setOn] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const l = useRef<Listener | null>(null);
  const supported = useSpeechSupport();
  useEffect(() => () => l.current?.stop(), []);

  function toggle() {
    if (on) return l.current?.stop();
    setErr(null);
    setOn(true);
    l.current = listen({
      onInterim: (t) => onInterim?.(t),
      onFinal: (t) => {
        onInterim?.("");
        onTranscript(t);
      },
      onError: (c) => setErr(speechErrorMessage(c) || null),
      onEnd: () => setOn(false),
    });
  }

  return (
    <div className="shrink-0">
      <button
        type="button"
        onClick={toggle}
        disabled={!supported}
        aria-pressed={on}
        aria-label={!supported ? "Voice input not supported in this browser" : on ? "Stop dictation" : "Dictate with your voice"}
        title={!supported ? "Voice input isn't supported in this browser. Type instead." : undefined}
        className={cx("grid h-12 w-12 place-items-center rounded-xl text-xl transition disabled:opacity-40", on ? "bg-dangersolid text-white pulse-ring" : "bg-brandsoft text-brandtext", className)}
      >
        🎙
      </button>
      {err && (
        <p role="alert" className="mt-1 max-w-48 text-xs text-danger">
          {err}
        </p>
      )}
    </div>
  );
}
