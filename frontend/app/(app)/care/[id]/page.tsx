"use client";
import { CheckCircle2, Footprints, Hourglass, Mic, Phone } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import FirstAidTriage from "@/components/FirstAidTriage";
import Map, { type MapMarker } from "@/components/Map";
import { Badge, Button, Card, ErrorState, Input, LoadingBlock, Modal, Notice, Toggle, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtEta, timeAgo } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import { cancelSpeech, listen, setSpeechOutputEnabled, speak, speechErrorMessage, speechOutputEnabled, useSpeechSupport, type Listener } from "@/lib/speech";
import type { CareReply, HelpRequest, IncidentState } from "@/lib/types";

interface Line {
  from: "you" | "nexa";
  text: string;
}
interface LogRow { id: number; kind: string; actor: string; content: string; at: string }

/* NEXA CARE information priority (top to bottom):
   1 incident status + persistent emergency state   2 call emergency services   3 current safety instruction + step actions
   4 help connection / helper ETA                   5 conversation & voice       6 secondary (map, state, audit log)
   Emergency styling is scoped to panels 1-4; there is no decorative animation in this screen. */
export default function CarePage() {
  const { id } = useParams<{ id: string }>();
  const iid = Number(id);
  const router = useRouter();
  const inc = useQuery(() => api<IncidentState>(`/api/incidents/${iid}`), [iid]);
  const reqQ = useQuery(inc.data?.request_id ? () => api<HelpRequest>(`/api/requests/${inc.data!.request_id}`) : null, [inc.data?.request_id]);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [voiceOut, setVoiceOut] = useState(() => speechOutputEnabled());
  const [handsFree, setHandsFree] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [lastSaid, setLastSaid] = useState("");
  const [endOpen, setEndOpen] = useState(false);
  const [log, setLog] = useState<LogRow[] | null>(null);
  const l = useRef<Listener | null>(null);
  const spokenStep = useRef<string>("");
  const supported = useSpeechSupport();
  const s = inc.data;

  useEffect(() => () => { l.current?.stop(); cancelSpeech(); }, []);

  useLiveEvents((e) => {
    if (e.type === "incident_update" && e.incident_id === iid) {
      void inc.reload();
      void reqQ.reload();
    }
  }, [iid]);
  // slow fallback refresh in case the socket is down
  useEffect(() => {
    const t = setInterval(() => { void inc.reload(); void reqQ.reload(); }, 15000);
    return () => clearInterval(t);
  }, [inc, reqQ]);

  // read the first instruction aloud when the screen opens (later turns are spoken with the reply)
  useEffect(() => {
    if (s?.status === "ACTIVE" && s.current_instruction && !spokenStep.current) {
      spokenStep.current = s.current_instruction;
      setLines([{ from: "nexa", text: `I'm here with you. ${s.current_instruction}` }]);
      speak(`I'm here with you. ${s.current_instruction}`);
    }
  }, [s?.status, s?.current_instruction]);

  const apply = useCallback((r: CareReply, autoListen = true) => {
    inc.setData(r.incident);
    setLines((x) => [...x, { from: "nexa", text: r.speech }]);
    spokenStep.current = r.incident.current_instruction ?? spokenStep.current;
    void reqQ.reload();
    speak(r.speech, { onEnd: () => autoListen && handsFree && supported && r.incident.status === "ACTIVE" && startListening() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handsFree, supported]);

  async function call<T extends CareReply>(fn: () => Promise<T>, userText?: string) {
    setBusy(true);
    setErr(null);
    if (userText) { setLines((x) => [...x, { from: "you", text: userText }]); setLastSaid(userText); }
    try {
      apply(await fn());
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const say = (t: string) => call(() => api<CareReply>(`/api/incidents/${iid}/say`, { method: "POST", body: { text: t } }), t);

  function startListening() {
    setErr(null);
    cancelSpeech();
    setListening(true);
    l.current = listen({
      onInterim: setInterim,
      onFinal: (t) => { setInterim(""); void say(t); },
      onError: (c) => { const m = speechErrorMessage(c); if (m && c !== "no-speech") setErr(m); },
      onEnd: () => setListening(false),
    });
  }

  if (inc.loading) return <LoadingBlock label="Connecting to NEXA CARE…" />;
  if (inc.error || !s) return <ErrorState message={inc.error ?? "Incident not found"} onRetry={inc.reload} />;

  const active = s.status === "ACTIVE";
  const req = reqQ.data;
  const notified = (req?.recipients ?? []).filter((r) => r.state === "NOTIFIED").length;
  const a = req?.assignments?.[0];
  const markers: MapMarker[] = [];
  if (req?.lat != null && req.lng != null) markers.push({ id: "me", lat: req.lat, lng: req.lng, kind: "me", label: "Your location" });
  if (a?.lat != null && a.lng != null) markers.push({ id: "h", lat: a.lat, lng: a.lng, kind: "helper", label: a.helper.name, detail: a.eta_minutes ? `ETA ${fmtEta(a.eta_minutes)}` : undefined });
  const helpStatus = a
    ? a.status === "ARRIVED" ? `${a.helper.name} has arrived.` : `${a.helper.name} accepted your request.${a.eta_minutes != null ? ` Estimated arrival: ${Math.round(a.eta_minutes)} minutes.` : ""}`
    : notified > 0 ? `Looking for help. ${notified} nearby helper${notified === 1 ? "" : "s"} and your circle have been alerted.` : "Looking for help. Widening the search.";

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {/* 1. status strip: always visible, words first */}
      <div className="emergency-strip flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3" role="status">
        <span className="text-lg font-extrabold">⬢ CRITICAL INCIDENT</span>
        <span className="font-bold">{active ? "ACTIVE" : s.status}</span>
        <span>{s.incident_id}</span>
        <span className="ml-auto text-sm font-bold">{s.emergency_services_contacted ? "✓ You contacted emergency services" : s.emergency_services_advised ? "▲ Please call emergency services" : ""}</span>
      </div>

      {!active && (
        <Card className="text-center">
          <h1 className="text-2xl font-extrabold">{s.status === "RESOLVED" ? "NEXA CARE has ended." : "NEXA CARE was stopped."}</h1>
          <p className="mt-1">I&apos;m glad help is with you. Please follow their guidance.</p>
          <div className="mt-4 flex flex-wrap justify-center gap-3">
            {s.request_id && <Link href={`/requests/${s.request_id}`} className="clay-btn inline-flex min-h-12 items-center bg-brand px-5 text-brandink">View request</Link>}
            <Link href="/" className="clay-btn clay-btn-secondary inline-flex min-h-12 items-center px-5">Home</Link>
          </div>
        </Card>
      )}

      {active && (
        <>
          {/* 2. emergency services */}
          <section className="emergency-panel p-4" aria-label="Emergency services">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <a href={`tel:${s.emergency_number}`} className="emergency-btn flex min-h-20 items-center justify-center gap-3 px-5 text-xl">
                <Phone aria-hidden size={24} /> CALL EMERGENCY SERVICES ({s.emergency_number})
              </a>
              <Button variant="emergency-secondary" size="xl" disabled={s.emergency_services_contacted || busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/escalate`, { method: "POST", body: { emergency_contacted: true, note: "user reports calling emergency services" } }))}>
                {s.emergency_services_contacted ? "✓ I HAVE CALLED" : "I HAVE CALLED"}
              </Button>
            </div>
            <p className="mt-3 text-sm font-semibold">{s.disclaimer}</p>
          </section>

          {/* 3. current instruction and what to do */}
          <section className="emergency-panel p-5" aria-label="Current instruction">
            {s.protocol_finished ? (
              <p className="text-2xl font-extrabold leading-snug">That was the last step. Stay where you are. Help is on the way, and I&apos;ll stay with you.</p>
            ) : (
              <>
                <p className="text-sm font-extrabold uppercase tracking-wide">{s.protocol_title} · STEP {s.current_step} OF {s.total_steps}</p>
                <p className="mt-2 text-2xl font-extrabold leading-snug sm:text-3xl" aria-live="assertive">{s.current_instruction}</p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <Button variant="emergency" size="xl" disabled={busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/step-complete`, { method: "POST", body: { step: s.current_step } }), "Done")}>✓ DONE, NEXT STEP</Button>
                  <Button variant="emergency-secondary" size="xl" disabled={busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/step-complete`, { method: "POST", body: { unable: true } }), "I can't do that")}>I CAN&apos;T DO THIS</Button>
                </div>
              </>
            )}
            <ol className="mt-4 flex flex-wrap gap-2" aria-label="Step progress">
              {Array.from({ length: s.total_steps }, (_, i) => i + 1).map((n) => {
                const done = s.completed_steps.includes(n), skipped = s.skipped_steps.includes(n), now = n === s.current_step && !s.protocol_finished;
                return (
                  <li key={n} className={cx("grid min-h-9 min-w-9 place-items-center rounded-lg border-2 px-2 text-sm font-extrabold", now ? "border-[#8f1111] bg-[#8f1111] text-white" : "border-[#1a0000]")}>
                    <span className="sr-only">Step {n}: {done ? "done" : skipped ? "skipped" : now ? "current" : "to do"}</span>
                    <span aria-hidden>{done ? `✓${n}` : skipped ? `↷${n}` : n}</span>
                  </li>
                );
              })}
            </ol>
          </section>

          {/* 4. help connection */}
          <section className="emergency-panel p-4" aria-label="Help status" aria-live="polite">
            <div className="flex items-center gap-4">
              <span aria-hidden>{a?.status === "ARRIVED" ? <CheckCircle2 size={34} /> : a ? <Footprints size={34} /> : <Hourglass size={34} />}</span>
              <div className="min-w-0 flex-1">
                <p className="text-lg font-extrabold">{helpStatus}</p>
                {a && <p className="text-sm">{a.helper.certifications.join(", ") || "Verified nearby helper"}</p>}
              </div>
              {a && a.status !== "ARRIVED" && a.eta_minutes != null && <div className="text-right"><p className="text-4xl font-extrabold tabular-nums">{Math.round(a.eta_minutes)}</p><p className="text-sm font-bold">min away</p></div>}
            </div>
          </section>

          {/* 5. conversation and voice (secondary to the instruction) */}
          <Card>
            <h2 className="mb-2 text-lg font-bold">Talk to NEXA</h2>
            <div className="max-h-52 space-y-2 overflow-y-auto" aria-live="polite" aria-label="Conversation">
              {lines.map((x, i) => <p key={i} className={cx("max-w-[90%] rounded-2xl px-3.5 py-2 text-[15px]", x.from === "you" ? "ml-auto bg-brand text-brandink" : "clay-well")}><span className="sr-only">{x.from === "you" ? "You: " : "NEXA: "}</span>{x.text}</p>)}
              {interim && <p className="ml-auto max-w-[90%] rounded-2xl bg-brand px-3.5 py-2 italic text-brandink">{interim}</p>}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {["I feel dizzy", "It's getting worse", "Repeat that", "Where is the helper?"].map((q) => <Button key={q} variant="secondary" size="sm" disabled={busy} onClick={() => void say(q)}>{q}</Button>)}
              <Button variant="success" size="sm" disabled={busy} onClick={() => void say("Help has arrived")}>✓ Help has arrived</Button>
            </div>
            {err && <Notice tone="danger" className="mt-3">{err}</Notice>}
            <form className="mt-3 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (t) { setText(""); void say(t); } }}>
              <button type="button" onClick={() => (listening ? l.current?.stop() : startListening())} disabled={!supported} aria-pressed={listening} aria-label={supported ? (listening ? "Stop listening" : "Talk to NEXA by voice") : "Voice not supported in this browser. Type instead."} className={cx("clay-btn grid h-14 w-14 shrink-0 place-items-center !rounded-full text-2xl disabled:opacity-50", listening ? "bg-dangersolid text-white" : "bg-brand text-brandink")}><Mic aria-hidden size={26} /></button>
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? "Listening…" : "Type to NEXA…"} aria-label="Message to NEXA" maxLength={500} />
              <Button type="submit" disabled={!text.trim() || busy}>Send</Button>
            </form>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Toggle checked={voiceOut} onChange={(v) => { setVoiceOut(v); setSpeechOutputEnabled(v); }} label="Speak instructions aloud" description="Everything is also shown as text." />
              <Toggle checked={handsFree} onChange={setHandsFree} label="Hands-free" description="NEXA listens again after it speaks." />
            </div>
          </Card>

          {/* assistive visual first-aid check: opens (asking about the camera, never starting it) when an injury is described */}
          <FirstAidTriage incidentId={iid} emergencyNumber={s.emergency_number} hint={lastSaid} onEscalate={() => void call(() => api<CareReply>(`/api/incidents/${iid}/escalate`, { method: "POST", body: { emergency_contacted: false, note: "first-aid check: more help requested" } }))} />
        </>
      )}

      {/* 6. secondary */}
      {markers.length > 0 && <Card className="!p-2"><Map center={[markers[0].lat, markers[0].lng]} zoom={15} markers={markers} fitToMarkers className="h-60" label="Incident map" /></Card>}
      <Card>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
          {[["Status", s.status], ["Situation", s.situation.replace(/_/g, " ")], ["Protocol", s.current_protocol ? `${s.current_protocol} v${s.protocol_version}` : "—"], ["Location shared", s.location_shared ? "Yes, with your helper" : "No"], ["Escalation level", String(s.escalation_level)], ["Emergency services", s.emergency_services_contacted ? "You contacted them" : s.emergency_services_advised ? "Advised: please call" : "—"]].map(([k, v]) => (
            <div key={k}><dt className="font-semibold text-muted">{k}</dt><dd className="font-bold">{v}</dd></div>
          ))}
        </dl>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button variant="secondary" size="sm" onClick={async () => { try { setLog(await api<LogRow[]>(`/api/incidents/${iid}/log`)); } catch (e) { setErr(errorMessage(e)); } }}>View audit log</Button>
          {active && <Button variant="secondary" size="sm" onClick={() => setEndOpen(true)}>End NEXA CARE</Button>}
        </div>
        {log && <ul className="clay-well mt-3 space-y-1 p-3 text-xs">{log.map((r) => <li key={r.id}><b>{r.kind}</b> <span className="text-muted">({r.actor}, {timeAgo(r.at)})</span> {r.content}</li>)}</ul>}
      </Card>
      <Badge tone="info" icon="ℹ">NEXA connects you with neighbours and guides you with approved first-aid steps.</Badge>

      <Modal open={endOpen} onClose={() => setEndOpen(false)} title="End NEXA CARE?">
        <p>Choose what happened. Cancelling also cancels the alert to helpers.</p>
        <div className="mt-4 grid gap-3">
          <Button variant="success" onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/close`, { method: "POST", body: { resolution: "RESOLVED", reason: "user confirmed safe / help arrived" } })).then(() => setEndOpen(false))}>Help has arrived / I&apos;m safe</Button>
          <Button variant="danger" onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/close`, { method: "POST", body: { resolution: "CANCELLED", reason: "user stopped care" } })).then(() => { setEndOpen(false); router.push("/"); })}>Cancel: false alarm</Button>
          <Button variant="secondary" onClick={() => setEndOpen(false)}>Keep NEXA CARE going</Button>
        </div>
      </Modal>
    </div>
  );
}
