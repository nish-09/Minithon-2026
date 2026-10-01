"use client";
import { Camera, History, ImagePlus, Mic, Phone, Send, Settings, Square, Video, Volume2, VolumeX, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { emotionFromText, type Emotion } from "@/lib/emotion";
import { useLocation } from "@/lib/hooks";
import { photoFromFile, type Photo } from "@/lib/image";
import { VISIBLE_SIGNS } from "@/lib/triage";
import { cancelSpeech, listen, speak, speechErrorMessage, speechOutputEnabled, setSpeechOutputEnabled, useSpeechSupport, type Listener } from "@/lib/speech";
import type { MatchResult, VoiceResult } from "@/lib/types";
import { NexaAvatar } from "./NexaAvatar";
import { NexaCamera } from "./NexaCamera";
import { NexaLive } from "./NexaLive";
import { Avatar, Notice, Toggle, cx } from "./ui";

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
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [camOpen, setCamOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [attachErr, setAttachErr] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [looking, setLooking] = useState(false);
  const liveRef = useRef(false);
  const liveFatal = useRef(false);
  const frameRef = useRef<(() => Photo | null) | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const listener = useRef<Listener | null>(null);
  const careTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const supported = useSpeechSupport();

  const mode: Mode = emergencyId !== null ? "emergency" : listening ? "listening" : matching ? "matching" : busy ? "understanding" : speaking ? "speaking" : "idle";

  // the character reflects what the person just said (concerned for emergencies, warm for thanks, thoughtful for questions)
  const lastUser = [...bubbles].reverse().find((b) => b.from === "user")?.text;
  const emotion: Emotion = mode === "emergency" ? "worried" : mode === "understanding" ? "thinking" : emotionFromText(lastUser);

  // Leaving plays the exit transition first; the parent only hides us afterwards.
  const exit = useCallback(
    (after?: () => void) => {
      if (closing) return;
      setClosing(true);
      listener.current?.stop();
      cancelSpeech();
      setTimeout(() => {
        setClosing(false);
        liveRef.current = false;
        setLive(false);
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

  async function send(raw: string, context: VoiceResult["context"] = ctx, shown?: string) {
    const t = raw.trim();
    if (!t || busy) return;
    setBusy(true);
    setChips([]);
    setMatches(null);
    setBubbles((b) => [...b, { from: "user", text: shown ?? t }]);
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
      const again = (!!r.context?.stage || liveRef.current) && supported && (voiceOut || liveRef.current);
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
    let heard = false;
    listener.current = listen({
      onInterim: setInterim,
      onFinal: (t) => {
        heard = true;
        setInterim("");
        void (liveRef.current ? sendLive(t, context) : send(t, context));
      },
      onError: (code) => {
        const m = speechErrorMessage(code);
        if (m) setMicError(m);
        if (code === "not-allowed" || code === "service-not-allowed" || code === "audio-capture" || code === "unsupported") liveFatal.current = true;
      },
      onEnd: () => {
        setListening(false);
        setInterim("");
        // live mode is hands-free: keep listening through silence, but never talk over NEXA or loop on a blocked mic
        if (liveRef.current && !heard && !liveFatal.current) {
          setTimeout(() => {
            if (liveRef.current && !liveFatal.current && !window.speechSynthesis?.speaking) start(context);
          }, 500);
        }
      },
    });
  }

  /** One still frame -> what it visibly shows (null when picture analysis isn't available or is too slow). */
  async function see(p: Photo, timeoutMs = 100_000): Promise<string[] | null> {
    try {
      const r = await api<{ available: boolean; observations: string[] }>("/api/triage/vision", {
        method: "POST",
        body: { image_b64: p.b64, media_type: "image/jpeg", consent: true },
        timeoutMs,
      });
      if (!r.available) return null;
      return r.observations.map((k) => VISIBLE_SIGNS.find(([x]) => x === k)?.[1]?.toLowerCase()).filter((x): x is string => !!x);
    } catch {
      return null;
    }
  }

  /** Live turn: what you said plus a look at the camera right now. A slow look never holds up the conversation. */
  async function sendLive(t: string, context: VoiceResult["context"]) {
    const frame = frameRef.current?.() ?? null;
    let seen: string[] | null = null;
    if (frame) {
      setLooking(true);
      seen = await see(frame, 15_000);
      setLooking(false);
    }
    await send(seen?.length ? `${t} The live camera shows: ${seen.join(", ")}.` : t, context, t);
  }

  /** "Look now": NEXA reports what it can see on camera right away. */
  async function lookNow() {
    const frame = frameRef.current?.() ?? null;
    if (!frame || looking) return;
    listener.current?.stop();
    setLooking(true);
    const seen = await see(frame);
    setLooking(false);
    const msg = seen === null ? "I can't read the camera picture right now, but you can still tell me what's happening."
      : seen.length ? `I can see signs of: ${seen.join(", ")}. Tell me what happened and how you feel.`
      : "I can see you, but nothing worrying stands out. Tell me what's happening.";
    setBubbles((b) => [...b, { from: "nexa", text: msg }]);
    setSpeaking(true);
    speak(msg, { onEnd: () => { setSpeaking(false); if (liveRef.current && !liveFatal.current) start(); } });
  }

  function startLive() {
    liveFatal.current = false;
    liveRef.current = true;
    setLive(true);
    setAttachErr(null);
    setPhoto(null);
    start();
  }

  function stopLive() {
    liveRef.current = false;
    setLive(false);
    setLooking(false);
    listener.current?.stop();
  }

  async function pickFile(f?: File) {
    if (!f) return;
    setAttachErr(null);
    try { setPhoto(await photoFromFile(f)); } catch (e) { setAttachErr(errorMessage(e)); }
  }

  /** Typed text goes straight through; with a photo attached it is analysed once (consented, not stored) and what it shows is added to the message. */
  async function submit() {
    if (busy || scanning) return;
    if (!photo) return void send(text);
    const note = text.trim();
    setScanning(true);
    setAttachErr(null);
    try {
      const got = await see(photo);
      const seen = got ?? [];
      if (got === null && !note) {
        setAttachErr("I can't read pictures right now. Describe what happened and I'll help from that.");
        return;
      }
      const base = note || "I need help. I'm sharing a photo.";
      setPhoto(null);
      await send(seen.length ? `${base} The photo shows: ${seen.join(", ")}.` : base);
    } catch (e) {
      setAttachErr(errorMessage(e));
    } finally {
      setScanning(false);
    }
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
        <NexaAvatar className="h-full w-full" mode={mode} emotion={emotion} />
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
      <div className="pointer-events-none absolute inset-x-3 bottom-[13rem] top-[42vh] z-10 flex flex-col items-start gap-3 overflow-y-auto lg:inset-x-auto lg:bottom-auto lg:left-8 lg:top-24 lg:max-h-[calc(100vh-20rem)] lg:w-[300px]">
        {started ? (
          <div className="nexa-glass pointer-events-auto flex max-w-full items-center gap-2.5 rounded-full py-1.5 pl-1.5 pr-4">
            <span aria-hidden className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand text-brandink", wave && "pulse-ring")}>
              <Mic size={15} />
            </span>
            <p role="status" aria-live="polite" className="truncate text-sm font-semibold">
              {STATUS[mode]}
            </p>
          </div>
        ) : (
          <section aria-label="Talk to NEXA" className="rise nexa-glass pointer-events-auto w-full rounded-3xl p-4">
            <div className="flex items-center gap-2.5">
              <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-brand text-brandink">
                <Mic size={15} />
              </span>
              <h2 className="text-sm font-bold tracking-wide">Talk to NEXA</h2>
            </div>
            <p role="status" aria-live="polite" className="mt-3 text-xl font-bold leading-tight">
              {STATUS[mode]}
            </p>
            <p className="mt-1.5 text-[13px] leading-snug text-ink/75">Speak, type, take a photo or upload an image. Try “I need someone to help me move a cupboard.”</p>
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
              <button key={c} onClick={() => chip(c)} className="nexa-glass min-h-11 rounded-full px-4 text-[13px] font-semibold text-brandtext transition hover:bg-white/10">
                {c}
              </button>
            ))}
            {links.map((l) => (
              <button key={l.href} onClick={() => exit(() => router.push(l.href))} className="nexa-glass min-h-11 rounded-full px-4 text-[13px] font-semibold text-brandtext transition hover:bg-white/10">
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
          <section aria-label="Suggested helpers" className="rise nexa-glass pointer-events-auto w-full rounded-3xl p-4">
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

      {/* voice + typing + camera + photo: one tidy dock centred below the model */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex flex-col items-center gap-3 px-4 pb-4 sm:pb-6">

        <div className="pointer-events-auto flex items-center gap-3">
          <Wave active={wave} />
          <div className="flex flex-col items-center gap-1.5">
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
            <span aria-hidden className="nexa-text text-xs font-semibold tracking-wide">
              {listening ? "Tap to stop" : "Tap to talk"}
            </span>
          </div>
          <Wave active={wave} flip />
        </div>

        <div className="pointer-events-auto w-full max-w-md space-y-2">
          {photo && (
            <div className="rise nexa-glass flex items-center gap-3 rounded-2xl p-2 pr-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={photo.preview} alt="Photo you are about to send" className="h-14 w-14 shrink-0 rounded-xl object-cover" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{scanning ? "Looking at your photo…" : "Photo ready to send"}</p>
                <p className="text-xs text-ink/70">Sent once for analysis and not saved.</p>
              </div>
              <button type="button" onClick={() => setPhoto(null)} disabled={scanning} aria-label="Remove photo" className="grid h-9 w-9 shrink-0 place-items-center rounded-full transition hover:bg-white/10 disabled:opacity-40">
                <X aria-hidden size={18} />
              </button>
            </div>
          )}
          {attachErr && <p role="alert" className="nexa-glass rounded-2xl px-4 py-2 text-sm">{attachErr}</p>}

          <form
            className="nexa-glass flex items-center gap-1 rounded-full p-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <DockButton label="Take a photo with the camera" onClick={() => { setAttachErr(null); setCamOpen(true); }}>
              <Camera aria-hidden size={20} />
            </DockButton>
            <DockButton label="Upload an image" onClick={() => fileRef.current?.click()}>
              <ImagePlus aria-hidden size={20} />
            </DockButton>
            <DockButton label={live ? "Stop live camera" : "Start live camera"} active={live} onClick={() => (live ? stopLive() : startLive())}>
              <Video aria-hidden size={20} />
            </DockButton>
            <input ref={fileRef} type="file" accept="image/*" hidden aria-label="Choose an image to send" onChange={(e) => { void pickFile(e.target.files?.[0]); e.target.value = ""; }} />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={listening ? "Listening…" : photo ? "Add a note (optional)…" : "Type a message..."}
              aria-label="Message to NEXA"
              maxLength={1000}
              className="min-w-0 flex-1 bg-transparent px-2 py-2 text-[15px] text-ink placeholder:text-ink/60 focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || scanning || (!text.trim() && !photo)}
              aria-label="Send"
              className="clay-btn flex h-11 items-center gap-1.5 !rounded-full bg-brand px-5 text-sm font-bold text-brandink disabled:opacity-40"
            >
              {busy || scanning ? "Sending…" : <>Send <Send aria-hidden size={15} /></>}
            </button>
          </form>
        </div>
      </div>

      {live && (
        <NexaLive
          frameRef={frameRef}
          looking={looking}
          onLook={() => void lookNow()}
          onStop={stopLive}
          onFail={(m) => { stopLive(); setMicError(m); }}
        />
      )}
      {camOpen && <NexaCamera onClose={() => setCamOpen(false)} onCapture={(p) => { setPhoto(p); setCamOpen(false); }} />}

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

function DockButton({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={active} className={cx("grid h-11 w-11 shrink-0 place-items-center rounded-full transition", active ? "bg-dangersolid text-white" : "text-brandtext hover:bg-white/10")}>
      {children}
    </button>
  );
}

function Bubble({ who, dim, children }: { who: "user" | "nexa"; dim?: boolean; children: React.ReactNode }) {
  const nexa = who === "nexa";
  return (
    <div className={cx("rise pointer-events-auto max-w-[92%] rounded-2xl px-3.5 py-2.5", nexa ? "nexa-glass rounded-tl-md" : "ml-auto rounded-tr-md bg-brand/90 text-brandink", dim && "opacity-60")}>
      <p className={cx("text-[10px] font-bold uppercase tracking-wider", nexa ? "text-brandtext" : "text-brandink/70")}>{nexa ? "NEXA" : "You"}</p>
      <p className="mt-0.5 text-[13.5px] leading-snug">{children}</p>
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
