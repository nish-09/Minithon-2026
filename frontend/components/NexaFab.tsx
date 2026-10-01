"use client";
import { Ear, EarOff, Mic } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { listenForWake, useSpeechSupport } from "@/lib/speech";
import { cx } from "./ui";

const KEY = "nexa_wake_word";
const WAKE = /\b(?:hey|hi|ok|okay|hello)[\s,]+(?:nexa|nexus|nex a|next a|nekta|nexta)\b[\s,.!?]*(.*)/i;

/* Floating "Talk to NEXA" button (bottom right) plus an opt-in "Hey NEXA" wake phrase.
   The wake phrase is ON by default (the browser asks for microphone permission; the person can turn it off and that is remembered) and listening is paused
   while the NEXA screen is open. Audio is handled by the browser's speech recognition; nothing is recorded by NEXA. */
export default function NexaFab({ onOpen, hidden }: { onOpen: (initialText?: string) => void; hidden: boolean }) {
  const supported = useSpeechSupport();
  const [wake, setWake] = useState(() => { try { return typeof window !== "undefined" && localStorage.getItem(KEY) !== "0"; } catch { return typeof window !== "undefined"; } });
  const [note, setNote] = useState<string | null>(null);
  const openRef = useRef(onOpen);
  useEffect(() => { openRef.current = onOpen; });

  useEffect(() => {
    if (!wake || hidden || !supported) return;
    const l = listenForWake({
      onTranscript: (t) => {
        const m = WAKE.exec(t);
        if (m) openRef.current(m[1]?.trim() || undefined);
      },
      onFatal: () => { setWake(false); setNote("Microphone is blocked, so “Hey NEXA” is off. Allow the microphone to use it."); try { localStorage.setItem(KEY, "0"); } catch { /* ignore */ } },
    });
    return () => l?.stop();
  }, [wake, hidden, supported]);

  function toggle() {
    const v = !wake;
    setWake(v);
    setNote(v ? "Listening for “Hey NEXA”. Say it any time." : "“Hey NEXA” is off.");
    try { localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* ignore */ }
    setTimeout(() => setNote(null), 4000);
  }

  if (hidden) return null;
  return (
    <div className="fixed bottom-5 right-4 z-40 flex flex-col items-end gap-2 sm:right-6">
      {note && <p role="status" className="clay-card max-w-[16rem] px-3 py-2 text-sm font-semibold">{note}</p>}
      {supported && (
        <button type="button" onClick={toggle} aria-pressed={wake} aria-label={wake ? "Turn off Hey NEXA wake phrase" : "Turn on Hey NEXA wake phrase"}
          className={cx("clay-btn clay-btn-secondary flex h-11 items-center gap-1.5 !rounded-full px-3 text-sm font-bold", wake && "!bg-mint")}>
          {wake ? <Ear aria-hidden size={18} /> : <EarOff aria-hidden size={18} />} Hey NEXA: {wake ? "on" : "off"}
        </button>
      )}
      <button type="button" onClick={() => onOpen()} aria-label="Talk to NEXA" className="clay-btn flex h-16 items-center gap-2 !rounded-full bg-lavender px-6 text-base">
        <Mic aria-hidden size={24} /> Talk to NEXA
      </button>
    </div>
  );
}
