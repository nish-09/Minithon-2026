"use client";
import { History, Mic, Phone, Settings, Square, Volume2, VolumeX, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useLocation } from "@/lib/hooks";
import { cancelSpeech, listen, speak, speechErrorMessage, speechOutputEnabled, setSpeechOutputEnabled, useSpeechSupport, type Listener } from "@/lib/speech";
import type { MatchResult, VoiceResult } from "@/lib/types";
import { NexaAvatar } from "./NexaAvatar";
import { Avatar, Button, Notice, Toggle, cx } from "./ui";

interface Bubble {
  from: "user" | "nexa";
  text: string;
}

type Mode = "idle" | "listening" | "understanding" | "matching" | "speaking" | "emergency";

const GREETING: Bubble = { from: "nexa", text: "Hi, I'm NEXA. Tell me what you need, for example: “I need someone to help me move a cupboard.”" };

const STATUS: Record<Mode, string> = {
  idle: "How can I help?",
  listening: "Listening...",
  understanding: "Understanding your request...",
  matching: "Finding suitable nearby helpers...",
  speaking: "NEXA is speaking...",
  emergency: "Emergency detected. NEXA CARE is active.",
};

const EXIT_MS = 320;

/** Full-screen NEXA AI mode. Voice is the primary input, but every turn can be typed and failures never dead-end. */
export function NexaMode({ open, onClose, initialText }: { open: boolean; onClose: () => void; initialText?: string }) {
  const router = useRouter();
  const loc = useLocation();
  const [closing, setClosing] = useState(false);
  const [bubbles, setBubbles] = useState<Bubble[]>([GREETING]);
  const [ctx, setCtx] = useState<VoiceResult["context"]>({});
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [matching, setMatching] = useState(false);
  const [emergencyId, setEmergencyId] = useState<number | null>(null);
  const [matches, setMatches] = useState<{ requestId: number; list: MatchResult[] } | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [share, setShare] = useState(true);
  const [voiceOut, setVoiceOut] = useState(() => speechOutputEnabled());
  const [chips, setChips] = useState<string[]>([]);
  const [links, setLinks] = useState<{ href: string; label: string }[]>([]);
  const [panel, setPanel] = useState<"history" | "settings" | null>(null);
  const listener = useRef<Listener | null>(null);
  const careTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const supported = useSpeechSupport();

  const mode: Mode = emergencyId !== null ? "emergency" : listening ? "listening" : matching ? "matching" : busy ? "understanding" : speaking ? "speaking" : "idle";

  // Leaving plays the exit transition first; the parent only hides us afterwards.
  const exit = useCallback(
    (after?: () => void) => {
      if (closing) return;
      setClosing(true);
      listener.current?.stop();
      cancelSpeech();
      setTimeout(() => {
        setClosing(false);
        setPanel(null);
        onClose();
        after?.();
      }, EXIT_MS);
    },
    [closing, onClose],
  );

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      prev?.focus?.();
      listener.current?.stop();
      cancelSpeech();
      if (careTimer.current) clearTimeout(careTimer.current);
    };
  }, [open]);

  function openCare(id: number) {
    if (careTimer.current) clearTimeout(careTimer.current);
    exit(() => router.push(`/care/${id}`));
  }

  async function loadMatches(requestId: number) {
    setMatching(true);
    try {
      const r = await api<{ matches: MatchResult[] }>(`/api/matching/${requestId}?limit=4`);
      setMatches({ requestId, list: r.matches });
    } catch {
      // The panel is a bonus; the request itself already exists and is reachable from "Open request".
    } finally {
      setMatching(false);
    }
  }

  async function send(raw: string, context: VoiceResult["context"] = ctx) {
    const t = raw.trim();
    if (!t || busy) return;
    setBusy(true);
    setChips([]);
    setMatches(null);
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
      if (r.data?.request_id && r.actions.includes("request_created")) {
        nl.push({ href: `/requests/${r.data.request_id}`, label: "Open request" });
        void loadMatches(r.data.request_id);
      }
      if (r.actions.includes("choose_routing")) setChips(["Yes, ask them first", "No, find community help", "Let me choose"]);
      if (r.actions.includes("care") && r.data?.incident?.id) {
        const id: number = r.data.incident.id;
        setEmergencyId(id);
        careTimer.current = setTimeout(() => openCare(id), 3500);
      }
      if (r.actions.includes("open_custom")) nl.push({ href: `/request/new?mode=custom&text=${encodeURIComponent(r.context?.draft_text ?? "")}`, label: "Choose who to ask" });
      if (r.actions.includes("need_location")) setChips(["Use my location"]);
      setLinks(nl);
      const again = !!r.context?.stage && supported && voiceOut;
      setSpeaking(true);
      speak(r.speech, {
        onEnd: () => {
          setSpeaking(false);
          if (again) start(r.context);
        },
      });
    } catch (e) {
      setBubbles((b) => [...b, { from: "nexa", text: `Sorry, that didn't work. ${errorMessage(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  function start(context: VoiceResult["context"] = ctx) {
    setMicError(null);
    cancelSpeech();
    setSpeaking(false);
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

  if (!open) return null;

  const lastNexa = [...bubbles].reverse().find((b) => b.from === "nexa") ?? GREETING;
  const wave = mode === "listening" || mode === "speaking";
  const started = bubbles.some((b) => b.from === "user");
  const helpers = matches && matches.list.length > 0 ? matches.list : null;

  return (
    <div
      ref={root}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label="NEXA AI mode"
      onKeyDown={(e) => e.key === "Escape" && exit()}
      className={cx("nexa-mode fixed inset-0 z-[3000] overflow-hidden text-ink outline-none", closing ? "nexa-mode-out" : "nexa-mode-in")}
      data-mode={mode}
    >
      {/* the model fills the whole viewport; every other piece floats directly over it */}
      <div className={cx("nexa-model absolute inset-0", mode === "speaking" && "nexa-speaking", mode === "listening" && "nexa-listening")}>
        <NexaAvatar className="h-full w-full" />
      </div>
      {/* state tint + edge glow; never intercepts input */}
      <div aria-hidden className="nexa-ambient pointer-events-none absolute inset-0" />

      {/* top-left: branding floats over the scene */}
      <div className="pointer-events-none absolute left-4 top-4 z-10 sm:left-8 sm:top-6">
        <h1 className="text-2xl font-extrabold tracking-tight text-brandtext sm:text-3xl">NEXA</h1>
        <p className="text-xs font-medium text-ink/70 sm:text-sm">Your neighborhood, when you need it most.</p>
      </div>

      {/* top-right: glass controls */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2 sm:right-6 sm:top-5">
        <IconButton label="Conversation history" pressed={panel === "history"} onClick={() => setPanel(panel === "history" ? null : "history")}>
          <History aria-hidden size={20} />
        </IconButton>
        <IconButton
          label={voiceOut ? "Mute NEXA's voice" : "Unmute NEXA's voice"}
          pressed={!voiceOut}
          onClick={() => {
            const v = !voiceOut;
            setVoiceOut(v);
            setSpeechOutputEnabled(v);
          }}
        >
          {voiceOut ? <Volume2 aria-hidden size={20} /> : <VolumeX aria-hidden size={20} />}
        </IconButton>
        <IconButton label="Settings" pressed={panel === "settings"} onClick={() => setPanel(panel === "settings" ? null : "settings")}>
          <Settings aria-hidden size={20} />
        </IconButton>
        <IconButton label="Exit NEXA mode" onClick={() => exit()}>
          <X aria-hidden size={20} />
        </IconButton>
      </div>

      {/* history / settings: small glass panel, only when asked for */}
      {panel && (
        <aside aria-label={panel === "history" ? "Conversation history" : "Settings"} className="rise nexa-glass absolute right-3 top-[4.5rem] z-20 flex max-h-[60vh] w-[min(22rem,calc(100vw-1.5rem))] flex-col rounded-3xl p-4 sm:right-6 sm:top-20">
          <h2 className="mb-3 text-base font-bold">{panel === "history" ? "Conversation" : "Settings"}</h2>
          {panel === "history" ? (
            <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto">
              {bubbles.map((b, i) => (
                <li key={i} className={cx("max-w-[90%] rounded-2xl px-3 py-2 text-sm", b.from === "user" ? "ml-auto bg-brand text-brandink" : "bg-white/10")}>
                  <span className="sr-only">{b.from === "user" ? "You: " : "NEXA: "}</span>
                  {b.text}
                </li>
              ))}
            </ul>
          ) : (
            <div className="space-y-4">
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
          )}
        </aside>
      )}

      {/* Left rail of separate floating pieces (not a sidebar): a small "Talk to NEXA" card, then one glass
          bubble per message. The model stays centred and nothing is placed over it. */}
      <div className="pointer-events-none absolute inset-x-3 bottom-[11.5rem] top-[42vh] z-10 flex flex-col items-start gap-2 overflow-y-auto lg:inset-x-auto lg:bottom-auto lg:left-8 lg:top-24 lg:max-h-[calc(100vh-18rem)] lg:w-[260px]">
        {started ? (
          <div className="nexa-text pointer-events-auto flex max-w-full items-center gap-2">
            <span aria-hidden className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand text-brandink", wave && "pulse-ring")}>
              <Mic size={14} />
            </span>
            <p role="status" aria-live="polite" className="truncate text-sm font-bold">
              {STATUS[mode]}
            </p>
          </div>
        ) : (
          <section aria-label="Talk to NEXA" className="rise nexa-text pointer-events-auto w-full">
            <div className="flex items-center gap-2">
              <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-brand text-brandink">
                <Mic size={14} />
              </span>
              <h2 className="text-sm font-extrabold">Talk to NEXA</h2>
            </div>
            <p role="status" aria-live="polite" className="mt-1.5 text-base font-bold leading-tight">
              {STATUS[mode]}
            </p>
            <p className="mt-1 text-xs text-ink/70">Tap the mic or type below. Try “I need someone to help me move a cupboard.”</p>
          </section>
        )}

        {started &&
          bubbles.slice(-4).map((b, i, a) => (
            <Bubble key={`${bubbles.length}-${i}`} who={b.from} dim={i < a.length - 2}>
              {b.text}
            </Bubble>
          ))}
        {!started && <Bubble who="nexa">{lastNexa.text}</Bubble>}
        {interim && (
          <Bubble who="user">
            <em>{interim}</em>
          </Bubble>
        )}

        {(chips.length > 0 || links.length > 0) && (
          <div className="pointer-events-auto flex flex-col items-start gap-2">
            {chips.map((c) => (
              <button key={c} onClick={() => chip(c)} className="nexa-text min-h-11 rounded-full border border-white/40 bg-white/10 px-4 text-[13px] font-semibold text-brandtext backdrop-blur-sm">
                {c}
              </button>
            ))}
            {links.map((l) => (
              <button key={l.href} onClick={() => exit(() => router.push(l.href))} className="nexa-text min-h-11 rounded-full border border-white/40 bg-white/10 px-4 text-[13px] font-semibold text-brandtext backdrop-blur-sm">
                {l.label} →
              </button>
            ))}
          </div>
        )}

        {micError && <div className="nexa-light pointer-events-auto"><Notice tone="warn">{micError}</Notice></div>}
        {loc.status === "denied" && (
          <div className="nexa-light pointer-events-auto">
            <Notice tone="warn">
              Location is blocked, so I can&apos;t find people near you. <button className="underline" onClick={() => void loc.useSample()}>Use the sample location</button> instead.
            </Notice>
          </div>
        )}

        {helpers && (
          <section aria-label="Suggested helpers" className="rise nexa-text pointer-events-auto w-full border-l-2 border-white/30 pl-3">
            <p className="mb-2 text-sm font-bold">
              I found {helpers.length} suitable helper{helpers.length === 1 ? "" : "s"} nearby.
            </p>
            <ul className="grid gap-2">
              {helpers.map((m) => (
                <li key={m.helper.id} className="flex items-center gap-2">
                  <Avatar name={m.helper.name} src={m.helper.avatar_url} size={32} />
                  <div className="min-w-0 text-sm">
                    <p className="truncate font-bold">{m.helper.name}</p>
                    <p className="truncate text-xs text-ink/70">
                      {m.distance_km.toFixed(1)} km · ~{m.eta_minutes} min · trust {Math.round(m.trust_score)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* voice + typing: centred below the model */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex flex-col items-center gap-2 px-4 pb-4 sm:pb-6">

        <div className="pointer-events-auto flex items-center gap-3">
          <Wave active={wave} />
          <div className="flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={() => (listening ? listener.current?.stop() : start())}
              disabled={!supported}
              aria-pressed={listening}
              aria-label={supported ? (listening ? "Stop listening" : "Tap to talk") : "Voice input not supported in this browser"}
              title={supported ? "" : "Voice input isn't supported in this browser. Type instead."}
              className={cx("grid h-20 w-20 place-items-center rounded-full transition disabled:opacity-40", listening ? "bg-dangersolid text-white pulse-ring" : "clay-btn bg-brand text-brandink")}
            >
              {listening ? <Square aria-hidden size={26} /> : <Mic aria-hidden size={34} />}
            </button>
            <span aria-hidden className="nexa-text text-xs font-bold">
              {listening ? "Tap to stop" : "Tap to talk"}
            </span>
          </div>
          <Wave active={wave} flip />
        </div>

        <form
          className="pointer-events-auto flex w-full max-w-sm items-center gap-2 rounded-full border border-white/40 bg-white/10 py-1.5 pl-4 pr-1.5 backdrop-blur-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void send(text);
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={listening ? "Listening…" : "Type a message..."}
            aria-label="Message to NEXA"
            maxLength={1000}
            className="min-w-0 flex-1 bg-transparent py-2 text-[15px] text-ink placeholder:text-ink/60 focus:outline-none"
          />
          <Button type="submit" loading={busy} disabled={!text.trim()} className="!rounded-full">
            Send
          </Button>
        </form>
      </div>

      {/* emergency: flat, high contrast, immediate */}
      {emergencyId !== null && (
        <div role="alertdialog" aria-label="NEXA CARE emergency" className="emergency-strip !rounded-none absolute inset-0 z-30 flex flex-col items-center justify-center gap-5 p-6 text-center text-white">
          <p className="text-sm font-extrabold tracking-[0.3em]">NEXA CARE</p>
          <h2 className="text-3xl font-extrabold sm:text-4xl">Help is being arranged</h2>
          <p className="max-w-xl text-lg">{lastNexa.text}</p>
          <a href="tel:112" className="emergency-btn-secondary inline-flex min-h-16 items-center gap-3 px-8 text-2xl">
            <Phone aria-hidden size={26} /> Call emergency services (112)
          </a>
          <button type="button" onClick={() => openCare(emergencyId)} className="emergency-btn min-h-14 px-8 text-lg">
            Open NEXA CARE now
          </button>
          <p className="text-sm">Opening your care screen automatically…</p>
        </div>
      )}
    </div>
  );
}

function IconButton({ label, pressed, onClick, children }: { label: string; pressed?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={pressed} className={cx("nexa-glass grid h-11 w-11 place-items-center rounded-full transition", pressed && "!bg-lavender text-brandink")}>
      {children}
    </button>
  );
}

function Bubble({ who, dim, children }: { who: "user" | "nexa"; dim?: boolean; children: React.ReactNode }) {
  return (
    <div className={cx("rise nexa-text pointer-events-auto max-w-[92%] border-l-2 pl-3", who === "user" ? "ml-4 border-brand" : "border-white/30", dim && "opacity-70")}>
      <p className={cx("text-[10px] font-extrabold uppercase tracking-wider", who === "nexa" ? "text-brandtext" : "text-ink/70")}>{who === "nexa" ? "NEXA" : "You"}</p>
      <p className="mt-0.5 text-[13px] leading-snug">{children}</p>
    </div>
  );
}

/** Decorative waveform flanking the microphone. Animated, not driven by real audio levels. */
function Wave({ active, flip }: { active: boolean; flip?: boolean }) {
  return (
    <div aria-hidden className={cx("pointer-events-none flex h-14 w-16 items-center gap-1", flip ? "flex-row-reverse" : "justify-end")}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={cx("nexa-bar block w-1.5 rounded-full bg-brandtext", active && "nexa-bar-on")} style={{ animationDelay: `${i * 90}ms` }} />
      ))}
    </div>
  );
}
