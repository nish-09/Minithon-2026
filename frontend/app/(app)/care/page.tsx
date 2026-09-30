"use client";
import { Mic, Phone, Siren } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, LoadingBlock, Notice, Textarea, Toggle, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { SAMPLE_LOCATION, useLocation } from "@/lib/hooks";
import { cancelSpeech, listen, speak, speechErrorMessage, speechRecognitionSupported, type Listener } from "@/lib/speech";
import type { IncidentState } from "@/lib/types";

const VAGUE = /^\s*(?:hey\s+)?(?:nexa[,.!]?\s*)?(?:i need help|help me|help|please help|i need some help|i'?m hurt)[.!]?\s*$/i;

/** Voice-first emergency entry: "Nexa, I need help." -> NEXA asks what happened -> starts care. */
export default function CareStart() {
  const router = useRouter();
  const loc = useLocation();
  const [checking, setChecking] = useState(true);
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [share, setShare] = useState(true);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState("Tap the mic and tell me what happened.");
  const [error, setError] = useState<string | null>(null);
  const l = useRef<Listener | null>(null);
  const supported = typeof window !== "undefined" && speechRecognitionSupported();

  useEffect(() => {
    api<{ incident: IncidentState | null }>("/api/incidents/active")
      .then((r) => r.incident && router.replace(`/care/${r.incident.id}`))
      .catch(() => undefined)
      .finally(() => setChecking(false));
    return () => {
      l.current?.stop();
      cancelSpeech();
    };
  }, [router]);

  async function begin(t: string) {
    setError(null);
    if (!loc.coords) {
      setError("I need your location so helpers can reach you. Allow location or use the sample location below.");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ incident: { id: number } }>("/api/incidents", { method: "POST", body: { text: t, lat: loc.coords.lat, lng: loc.coords.lng, share_location: share } });
      router.replace(`/care/${r.incident.id}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  function startListening() {
    setError(null);
    cancelSpeech();
    setListening(true);
    l.current = listen({
      onInterim: setInterim,
      onFinal: (t) => {
        setInterim("");
        if (VAGUE.test(t)) {
          const q = "I'm here. What happened? Are you hurt?";
          setPrompt(q);
          speak(q, { onEnd: startListening });
        } else {
          setText(t);
          void begin(t);
        }
      },
      onError: (c) => setError(speechErrorMessage(c) || null),
      onEnd: () => setListening(false),
    });
  }

  if (checking) return <LoadingBlock />;
  return (
    <div className="px-0 py-2">
      <div className="mx-auto max-w-xl space-y-6 text-center">
        <div>
          <p className="text-sm font-extrabold uppercase tracking-widest text-danger">⬢ NEXA CARE · Emergency support</p>
          <h1 className="mt-2 text-3xl font-extrabold">Help is on the way. You&apos;re not alone.</h1>
          <p className="mt-2 text-muted">Tell me what happened. I&apos;ll alert your Trusted Circle and nearby first-aid helpers, and guide you step by step.</p>
        </div>

        <a href="tel:112" className="emergency-btn flex min-h-20 items-center justify-center gap-3 px-4 text-xl">
          <Phone aria-hidden size={24} /> CALL EMERGENCY SERVICES (112)
        </a>
        <p className="text-xs text-muted">NEXA connects you with neighbours. It does not replace emergency services. For serious injuries, call first.</p>

        <div>
          <button
            onClick={() => (listening ? l.current?.stop() : startListening())}
            disabled={!supported || busy}
            aria-pressed={listening}
            aria-label={listening ? "Stop listening" : "Tap to talk to NEXA"}
            className={cx("clay-btn mx-auto grid h-36 w-36 place-items-center !rounded-full text-6xl disabled:opacity-50", listening ? "bg-dangersolid text-white" : "bg-brand text-brandink")}
          >
            <Mic aria-hidden size={60} />
          </button>
          <p className="mt-4 min-h-6 text-lg font-medium" aria-live="polite">{listening ? interim || "Listening…" : prompt}</p>
          {!supported && <Notice tone="warn" className="mt-3 text-left">Voice input isn&apos;t supported in this browser. Type below instead.</Notice>}
        </div>

        <div className="space-y-3 text-left">
          <label htmlFor="care-text" className="text-sm font-medium">Or type what happened</label>
          <Textarea id="care-text" rows={3} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. I fell off my bike and my arm is bleeding" />
          <Toggle checked={share} onChange={setShare} label="Share my exact location with the helper who accepts" description="Recommended so help can find you." />
          {!loc.coords && (
            <Notice tone="warn">
              <p className="font-semibold">I don&apos;t have your location yet.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" onClick={loc.request} loading={loc.status === "asking"}>Use my location</Button>
                <Button size="sm" variant="secondary" onClick={() => void loc.useSample()}>Use sample location ({SAMPLE_LOCATION.label})</Button>
              </div>
            </Notice>
          )}
          {error && <Notice tone="danger">{error}</Notice>}
          <Button size="xl" variant="emergency" className="w-full" loading={busy} disabled={text.trim().length < 3} onClick={() => void begin(text.trim())}>
            <Siren aria-hidden size={22} /> Start NEXA CARE
          </Button>
        </div>
      </div>
    </div>
  );
}
