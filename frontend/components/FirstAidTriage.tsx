"use client";
import { Camera, CameraOff, Eye, HandHelping, Phone, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Notice, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { TRIGGER_RE, VISIBLE_SIGNS, type TriageResult } from "@/lib/triage";

/* Assistive first-aid check inside NEXA CARE. Not a diagnosis tool.
   Privacy: the camera is off until the person allows it, the preview stays on the device, and a frame is only
   sent (once, never stored) when they press "Analyse this frame". Everything works without camera or voice. */
export default function FirstAidTriage({ incidentId, emergencyNumber, hint, onEscalate }: {
  incidentId: number; emergencyNumber: string; hint: string; onEscalate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [desc, setDesc] = useState("");
  const [signs, setSigns] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [res, setRes] = useState<TriageResult | null>(null);
  const [step, setStep] = useState(0);
  const [camAsk, setCamAsk] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [camMsg, setCamMsg] = useState<string | null>(null);
  const [canAnalyse, setCanAnalyse] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastLevel = useRef<string | null>(null);

  // an injury described in the conversation opens the check and ASKS about the camera; it never starts it
  const [seenHint, setSeenHint] = useState("");
  if (hint !== seenHint) {
    setSeenHint(hint);
    if (hint && TRIGGER_RE.test(hint)) { setOpen(true); setDesc((d) => d || hint); setCamAsk(true); }
  }

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCamOn(false);
  }, []);
  useEffect(() => stopCamera, [stopCamera]);

  async function allowCamera() {
    setCamAsk(false);
    setCamMsg(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      streamRef.current = s;
      setCamOn(true);
      requestAnimationFrame(() => { if (videoRef.current) { videoRef.current.srcObject = s; void videoRef.current.play().catch(() => {}); } });
    } catch {
      setCamMsg("The camera isn't available or was blocked. No problem: you can tick what you can see below instead.");
    }
  }

  async function analyseFrame() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    setBusy(true); setErr(null);
    try {
      const c = document.createElement("canvas");
      const scale = Math.min(1, 640 / v.videoWidth);
      c.width = v.videoWidth * scale; c.height = v.videoHeight * scale;
      c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
      const b64 = c.toDataURL("image/jpeg", 0.7).split(",")[1];
      const r = await api<{ available: boolean; reason?: "not_configured" | "model_missing" | "failed"; model?: string; observations: string[] }>("/api/triage/vision", { method: "POST", body: { image_b64: b64, media_type: "image/jpeg", consent: true } });
      if (!r.available) {
        if (r.reason !== "failed") setCanAnalyse(false); // nothing to retry: hide the button for this session
        setCamMsg(r.reason === "not_configured"
          ? "Automatic picture analysis isn't set up on this server, so I can't read the camera for you. Your camera preview still works. Please tick what you can see below and I'll guide you from that."
          : r.reason === "model_missing"
            ? `The local picture model (${r.model}) isn't installed yet. Please tick what you can see below and I'll guide you from that.`
            : "I couldn't analyse that picture just now. You can try again, or tick what you can see below.");
      }
      else {
        setSigns((x) => Array.from(new Set([...x, ...r.observations])));
        setCamMsg(r.observations.length ? "I've ticked what I could see below. Please correct anything that's wrong." : "I couldn't clearly see anything specific. Please tick what you can see below.");
      }
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }

  async function run(nextAnswers = answers, nextSigns = signs) {
    setBusy(true); setErr(null);
    try {
      const r = await api<TriageResult>("/api/triage/assess", { method: "POST", body: { text: desc.slice(0, 500), observations: nextSigns, answers: nextAnswers, incident_id: incidentId } });
      if (lastLevel.current !== r.level) setStep(0);
      lastLevel.current = r.level;
      setRes(r);
      if (r.level === "CRITICAL") { stopCamera(); onEscalate(); } // clarity over analysis: stop the camera, surface emergency help
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const answer = (k: string, v: boolean) => { const a = { ...answers, [k]: v }; setAnswers(a); void run(a); };
  const toggleSign = (k: string) => setSigns((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k]));

  if (!open) {
    return (
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Eye aria-hidden size={22} />
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-bold">Visual first-aid check</h2>
            <p className="text-sm text-muted">Describe an injury and get step-by-step first-aid guidance. Camera is optional.</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>Start check</Button>
        </div>
      </Card>
    );
  }

  const crit = res && (res.level === "URGENT" || res.level === "CRITICAL");
  const shell = crit ? "emergency-panel p-5" : "clay-card p-5";
  return (
    <section className={cx(shell, "space-y-4")} aria-label="Visual first-aid check">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-bold">Visual first-aid check</h2>
        {camOn && <span role="status" className="ml-auto inline-flex items-center gap-1 rounded-full border-2 border-[#8f1111] px-2.5 py-0.5 text-xs font-extrabold"><span aria-hidden>●</span> CAMERA ON</span>}
      </div>
      <p className="text-sm">I can describe what may be happening and suggest first-aid steps. I can&apos;t diagnose, and this doesn&apos;t replace professional help.</p>

      {/* the emergency action is always one tap away */}
      <a href={`tel:${emergencyNumber}`} className={cx("flex min-h-14 items-center justify-center gap-2 px-4 text-lg", crit ? "emergency-btn" : "clay-btn clay-btn-secondary")}>
        <Phone aria-hidden size={20} /> Call emergency services ({emergencyNumber})
      </a>

      {camAsk && !camOn && (
        <div className="clay-well space-y-2 p-4" role="group" aria-label="Camera permission">
          <p className="font-semibold">Would you like to turn on your camera so I can check for visible signs of injury?</p>
          <p className="text-sm">I&apos;ll look for things like bleeding, swelling or an unusual position. The preview stays on your device. A single picture is only sent if you press &quot;Analyse this frame&quot;, and it is not saved. You can turn the camera off at any time.</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void allowCamera()}><Camera aria-hidden size={16} /> Allow camera</Button>
            <Button size="sm" variant="secondary" onClick={() => setCamAsk(false)}>No thanks, continue without camera</Button>
          </div>
        </div>
      )}
      {!camAsk && !camOn && (
        <Button size="sm" variant="secondary" onClick={() => setCamAsk(true)}><Camera aria-hidden size={16} /> Use camera (optional)</Button>
      )}
      {camOn && (
        <div className="space-y-2">
          <video ref={videoRef} muted playsInline className="max-h-64 w-full rounded-2xl border-2 border-linestrong bg-black object-cover" aria-label="Your camera preview. It stays on this device." />
          <div className="flex flex-wrap gap-2">
            {canAnalyse && <Button size="sm" disabled={busy} onClick={() => void analyseFrame()}>Analyse this frame</Button>}
            <Button size="sm" variant="secondary" onClick={stopCamera}><CameraOff aria-hidden size={16} /> Turn camera off</Button>
          </div>
        </div>
      )}
      {camMsg && <Notice tone="brand">{camMsg}</Notice>}

      <div>
        <label htmlFor="fa-desc" className="font-semibold">What happened?</label>
        <textarea id="fa-desc" value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={500} rows={2} placeholder="For example: I fell and my ankle is swollen" className="clay-input mt-1 w-full p-3" />
      </div>
      <fieldset>
        <legend className="font-semibold">What can you see? <span className="text-sm font-normal text-muted">(tick all that apply; leave empty if unsure)</span></legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {VISIBLE_SIGNS.map(([k, label]) => (
            <label key={k} className="clay-well flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2">
              <input type="checkbox" className="h-5 w-5" checked={signs.includes(k)} onChange={() => toggleSign(k)} /> {label}
            </label>
          ))}
        </div>
      </fieldset>
      <Button disabled={busy || (!desc.trim() && signs.length === 0)} onClick={() => void run()}>{res ? "Update assessment" : "Get first-aid guidance"}</Button>
      {err && <Notice tone="danger">{err}</Notice>}

      {res && (
        <div className="space-y-4" aria-live="polite">
          <div className={cx("rounded-2xl border-4 p-4", res.level === "CRITICAL" ? "border-[#8f1111]" : res.level === "URGENT" ? "border-[#a84300]" : "border-linestrong")}>
            <p className="flex items-center gap-2 text-sm font-extrabold uppercase tracking-wide">
              <ShieldAlert aria-hidden size={18} /> {res.level === "CRITICAL" ? "⬢ CRITICAL" : res.level === "URGENT" ? "▲ URGENT" : res.level === "MODERATE" ? "● MODERATE" : "○ LOW"}
            </p>
            <p className="mt-1 text-xl font-extrabold leading-snug">{res.summary}</p>
            {res.call_emergency && <p className="mt-2 font-bold">{res.level === "CRITICAL" ? "Call emergency services now. " : "Please get urgent medical help. "}I&apos;ve alerted your circle and nearby helpers, and I&apos;m staying with you.</p>}
          </div>

          <div>
            <h3 className="font-bold">Why this is {res.level.toLowerCase()}</h3>
            <ul className="mt-1 list-disc pl-5">{res.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>

          {res.questions.length > 0 && (
            <div className="clay-well space-y-2 p-4">
              <p className="font-bold">{res.questions[0].text}</p>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy} onClick={() => answer(res.questions[0].key, true)}>Yes</Button>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => answer(res.questions[0].key, false)}>No</Button>
              </div>
            </div>
          )}

          {res.steps.length > 0 && (
            <div className={cx("rounded-2xl p-4", crit ? "border-2 border-[#1a0000]" : "clay-well")}>
              <p className="text-sm font-extrabold uppercase tracking-wide">Step {step + 1} of {res.steps.length}</p>
              <p className="mt-1 text-2xl font-extrabold leading-snug" aria-live="assertive">{res.steps[Math.min(step, res.steps.length - 1)].text}</p>
              <div className="mt-3 flex gap-2">
                <Button variant={crit ? "emergency" : "primary"} size="lg" disabled={step >= res.steps.length - 1} onClick={() => setStep((s) => s + 1)}>Done, next step</Button>
                <Button variant={crit ? "emergency-secondary" : "secondary"} size="lg" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>Back</Button>
              </div>
            </div>
          )}

          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="font-bold">Observed</dt><dd>{res.observed.length ? res.observed.map((o) => <p key={o}>{o}</p>) : "Nothing visible has been reported."}</dd></div>
            <div><dt className="font-bold">Inferred (may be wrong)</dt><dd>{res.inferred.length ? res.inferred.map((o) => <p key={o}>{o}</p>) : "Nothing yet."}</dd></div>
            <div><dt className="font-bold">I can&apos;t tell</dt><dd>{res.unknown.map((o) => <p key={o}>{o}</p>)}</dd></div>
          </dl>

          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={onEscalate}><HandHelping aria-hidden size={16} /> Ask for more help nearby</Button>
          </div>
          <p className="text-xs">{res.limits}</p>
        </div>
      )}
    </section>
  );
}
