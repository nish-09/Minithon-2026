"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useLocation, useToast } from "@/lib/hooks";
import { cancelSpeech, listen, speak, speechErrorMessage, speechOutputEnabled, setSpeechOutputEnabled, useSpeechSupport, type Listener } from "@/lib/speech";
import type { VoiceResult } from "@/lib/types";
import { Button, Input, Modal, Notice, Toggle, cx } from "./ui";

interface Bubble {
  from: "user" | "nexa";
  text: string;
}

const GREETING: Bubble = { from: "nexa", text: "Hi, I'm NEXA. Tell me what you need, for example: “I need someone to help me move a cupboard.”" };

/** Conversational assistant. Voice is optional: every turn can be typed, and failures never dead-end. */
export function VoicePanel({ open, onClose, initialText }: { open: boolean; onClose: () => void; initialText?: string }) {
  const router = useRouter();
  const toast = useToast();
  const loc = useLocation();
  const [bubbles, setBubbles] = useState<Bubble[]>([GREETING]);
  const [ctx, setCtx] = useState<VoiceResult["context"]>({});
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [share, setShare] = useState(true);
  const [voiceOut, setVoiceOut] = useState(() => speechOutputEnabled());
  const [chips, setChips] = useState<string[]>([]);
  const [links, setLinks] = useState<{ href: string; label: string }[]>([]);
  const listener = useRef<Listener | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const supported = useSpeechSupport();

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [bubbles, interim]);
  useEffect(() => {
    if (!open) {
      listener.current?.stop();
      cancelSpeech();
    }
  }, [open]);

  async function send(raw: string, context: VoiceResult["context"] = ctx) {
    const t = raw.trim();
    if (!t || busy) return;
    setBusy(true);
    setChips([]);
    setBubbles((b) => [...b, { from: "user", text: t }]);
    setText("");
    try {
      const r = await api<VoiceResult>("/api/voice/command", {
        method: "POST",
        body: { text: t, lat: loc.coords?.lat, lng: loc.coords?.lng, share_location: share, context },
      });
      setBubbles((b) => [...b, { from: "nexa", text: r.speech }]);
      setCtx(r.context ?? {});
      const nl: { href: string; label: string }[] = [];
      if (r.data?.request_id && r.actions.includes("request_created")) nl.push({ href: `/requests/${r.data.request_id}`, label: "Open request" });
      if (r.actions.includes("choose_routing")) setChips(["Yes, ask them first", "No, find community help", "Let me choose"]);
      if (r.actions.includes("care") && r.data?.incident?.id) {
        toast.push({ kind: "emergency", title: "NEXA CARE is active", body: "Opening your care screen…" });
        setTimeout(() => {
          onClose();
          router.push(`/care/${r.data.incident.id}`);
        }, 900);
      }
      if (r.actions.includes("open_custom")) nl.push({ href: `/request/new?mode=custom&text=${encodeURIComponent(r.context?.draft_text ?? "")}`, label: "Choose who to ask" });
      if (r.actions.includes("need_location")) setChips(["Use my location"]);
      setLinks(nl);
      const again = !!r.context?.stage && supported && voiceOut;
      speak(r.speech, { onEnd: () => again && start(r.context) });
    } catch (e) {
      setBubbles((b) => [...b, { from: "nexa", text: `Sorry, that didn't work. ${errorMessage(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  function start(context: VoiceResult["context"] = ctx) {
    setMicError(null);
    cancelSpeech();
    setListening(true);
    listener.current = listen({
      onInterim: setInterim,
      onFinal: (t) => {
        setInterim("");
        void send(t, context);
      },
      onError: (code) => {
        const m = speechErrorMessage(code);
        if (m) setMicError(m);
      },
      onEnd: () => {
        setListening(false);
        setInterim("");
      },
    });
  }

  const sentInitial = useRef<string | null>(null);
  useEffect(() => {
    if (open && initialText && sentInitial.current !== initialText) {
      sentInitial.current = initialText;
      void send(initialText);
    }
    if (!open) sentInitial.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialText]);

  const chip = (c: string) => {
    if (c === "Use my location") return loc.request();
    void send(c === "Yes, ask them first" ? "Yes" : c === "No, find community help" ? "No, community" : "Let me choose");
  };

  return (
    <Modal open={open} onClose={onClose} title="Talk to NEXA" wide>
      <div className="flex h-[62vh] flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto pr-1" aria-live="polite" aria-label="Conversation">
          {bubbles.map((b, i) => (
            <div key={i} className={cx("max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-snug", b.from === "user" ? "ml-auto bg-brand text-brandink" : "bg-surface2")}>
              {b.text}
            </div>
          ))}
          {interim && <div className="ml-auto max-w-[85%] rounded-2xl bg-brand/60 px-4 py-2.5 text-brandink italic">{interim}</div>}
          {busy && <div className="w-16 rounded-2xl bg-surface2 px-4 py-2.5 text-muted">…</div>}
          {links.map((l) => (
            <Button key={l.href} variant="secondary" size="sm" onClick={() => { onClose(); router.push(l.href); }}>
              {l.label} →
            </Button>
          ))}
          <div ref={endRef} />
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 py-2">
            {chips.map((c) => (
              <button key={c} onClick={() => chip(c)} className="min-h-10 rounded-full border border-brand/40 bg-brandsoft px-4 text-sm font-medium text-brandtext">
                {c}
              </button>
            ))}
          </div>
        )}
        {micError && <Notice tone="warn" className="mb-2">{micError}</Notice>}
        {loc.status === "denied" && <Notice tone="warn" className="mb-2">Location is blocked, so I can&apos;t find people near you. <button className="underline" onClick={() => void loc.useSample()}>Use the sample location</button> instead.</Notice>}

        <form
          className="flex items-center gap-2 pt-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send(text);
          }}
        >
          <button
            type="button"
            onClick={() => (listening ? listener.current?.stop() : start())}
            disabled={!supported}
            aria-pressed={listening}
            aria-label={supported ? (listening ? "Stop listening" : "Start voice input") : "Voice input not supported in this browser"}
            title={supported ? "" : "Voice input isn't supported in this browser. Type instead."}
            className={cx("grid h-12 w-12 shrink-0 place-items-center rounded-full text-xl transition disabled:opacity-40", listening ? "bg-dangersolid text-white pulse-ring" : "bg-brand text-brandink")}
          >
            🎙
          </button>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? "Listening…" : "Type a message…"} aria-label="Message to NEXA" maxLength={1000} />
          <Button type="submit" loading={busy} disabled={!text.trim()}>
            Send
          </Button>
        </form>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <Toggle checked={share} onChange={setShare} label="Share exact location with my helper" description="Only with the person who accepts." />
          <Toggle
            checked={voiceOut}
            onChange={(v) => {
              setVoiceOut(v);
              setSpeechOutputEnabled(v);
            }}
            label="Speak replies aloud"
          />
        </div>
      </div>
    </Modal>
  );
}
