"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Map, { type MapMarker } from "@/components/Map";
import { Badge, Button, ErrorState, Input, LoadingBlock, Modal, Notice, Toggle, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtEta, timeAgo } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import { cancelSpeech, listen, setSpeechOutputEnabled, speak, speechErrorMessage, speechOutputEnabled, speechRecognitionSupported, type Listener } from "@/lib/speech";
import type { CareReply, HelpRequest, IncidentState } from "@/lib/types";

interface Line {
  from: "you" | "nexa";
  text: string;
}
interface LogRow { id: number; kind: string; actor: string; content: string; at: string }

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
  const [endOpen, setEndOpen] = useState(false);
  const [log, setLog] = useState<LogRow[] | null>(null);
  const l = useRef<Listener | null>(null);
  const spokenStep = useRef<string>("");
  const supported = typeof window !== "undefined" && speechRecognitionSupported();
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
    if (userText) setLines((x) => [...x, { from: "you", text: userText }]);
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
  if (req?.lat != null && req.lng != null) markers.push({ id: "me", lat: req.lat, lng: req.lng, emoji: "📍", color: "#ef4444", label: "You", pulse: active });
  if (a?.lat != null && a.lng != null) markers.push({ id: "h", lat: a.lat, lng: a.lng, emoji: "🧑‍⚕️", color: "#16a34a", label: a.helper.name, detail: a.eta_minutes ? `ETA ${fmtEta(a.eta_minutes)}` : undefined });

  return (
    <div className="emergency -mx-4 -my-5 min-h-[calc(100vh-4rem)] bg-bg px-4 py-5 text-ink sm:-mx-6 sm:px-6">
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="danger" className={cx(active && "pulse-ring")}>{active ? "● ACTIVE" : s.status}</Badge>
          <span className="text-sm text-muted">{s.incident_id} · {s.urgency}</span>
          <span className="ml-auto flex items-center gap-3 text-sm">
            <Toggle checked={voiceOut} onChange={(v) => { setVoiceOut(v); setSpeechOutputEnabled(v); }} label="Voice" />
          </span>
        </div>

        {active ? (
          <h1 className="text-2xl font-extrabold">Help is on the way. You&apos;re not alone.</h1>
        ) : (
          <div className="rounded-2xl bg-surface p-5 text-center">
            <p className="text-xl font-bold">{s.status === "RESOLVED" ? "NEXA CARE has ended." : "NEXA CARE was stopped."}</p>
            <p className="mt-1 text-muted">I&apos;m glad help is with you. Please follow their guidance.</p>
            <div className="mt-4 flex justify-center gap-2">
              {s.request_id && <Link href={`/requests/${s.request_id}`} className="rounded-xl bg-brand px-4 py-2.5 font-semibold text-brandink">View request</Link>}
              <Link href="/" className="rounded-xl border border-line px-4 py-2.5 font-semibold">Home</Link>
            </div>
          </div>
        )}

        {active && (
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <a href={`tel:${s.emergency_number}`} className="flex min-h-14 items-center justify-center gap-2 rounded-2xl bg-dangersolid px-5 text-lg font-extrabold text-white">📞 Call {s.emergency_number}</a>
            <Button variant="secondary" className="min-h-14" disabled={s.emergency_services_contacted || busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/escalate`, { method: "POST", body: { emergency_contacted: true, note: "user reports calling emergency services" } }))}>
              {s.emergency_services_contacted ? "✓ You called" : "I've called"}
            </Button>
          </div>
        )}

        {/* helper */}
        {active && (
          <div className="rounded-2xl border border-line bg-surface p-4" aria-live="polite">
            {a ? (
              <div className="flex items-center gap-4">
                <span className="text-3xl" aria-hidden>{a.status === "ARRIVED" ? "✅" : "🚶"}</span>
                <div className="flex-1">
                  <p className="text-lg font-semibold">{a.helper.name} {a.status === "ARRIVED" ? "has arrived" : "is on the way"}</p>
                  <p className="text-sm text-muted">{a.helper.certifications.join(", ") || "Verified nearby helper"}</p>
                </div>
                {a.status !== "ARRIVED" && a.eta_minutes != null && <div className="text-right"><p className="text-4xl font-extrabold tabular-nums">{Math.round(a.eta_minutes)}</p><p className="text-xs text-muted">min away</p></div>}
              </div>
            ) : (
              <p><b>Looking for help…</b> <span className="text-muted">{notified > 0 ? `${notified} nearby helper${notified === 1 ? "" : "s"} and your circle have been alerted.` : "Widening the search."}</span></p>
            )}
          </div>
        )}

        {/* current step */}
        {active && (
          <div className="rounded-2xl border-2 border-danger bg-surface p-5">
            {s.protocol_finished ? (
              <p className="text-xl font-semibold">That was the last step. Stay where you are. Help is on the way, and I&apos;ll stay with you.</p>
            ) : (
              <>
                <p className="text-xs font-bold uppercase tracking-wider text-danger">{s.protocol_title} · step {s.current_step} of {s.total_steps}</p>
                <p className="mt-2 text-xl font-semibold leading-snug sm:text-2xl" aria-live="assertive">{s.current_instruction}</p>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <Button size="lg" variant="success" disabled={busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/step-complete`, { method: "POST", body: { step: s.current_step } }), "Done")}>✓ Done</Button>
                  <Button size="lg" variant="secondary" disabled={busy} onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/step-complete`, { method: "POST", body: { unable: true } }), "I can't do that")}>I can&apos;t do this</Button>
                </div>
              </>
            )}
            <div className="mt-4 flex flex-wrap gap-1.5" aria-label="Progress">
              {Array.from({ length: s.total_steps }, (_, i) => i + 1).map((n) => (
                <span key={n} title={`Step ${n}`} className={cx("grid h-7 w-7 place-items-center rounded-full text-xs font-bold", s.completed_steps.includes(n) ? "bg-oksolid text-white" : s.skipped_steps.includes(n) ? "bg-warn text-black" : n === s.current_step ? "bg-dangersolid text-white" : "bg-surface2 text-muted")}>{s.completed_steps.includes(n) ? "✓" : n}</span>
              ))}
            </div>
          </div>
        )}

        {/* conversation */}
        {active && (
          <div className="rounded-2xl border border-line bg-surface p-4">
            <div className="max-h-52 space-y-2 overflow-y-auto" aria-live="polite" aria-label="Conversation">
              {lines.map((x, i) => <p key={i} className={cx("max-w-[90%] rounded-2xl px-3.5 py-2 text-[15px]", x.from === "you" ? "ml-auto bg-brand text-brandink" : "bg-surface2")}>{x.text}</p>)}
              {interim && <p className="ml-auto max-w-[90%] rounded-2xl bg-brand/60 px-3.5 py-2 italic">{interim}</p>}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {["I feel dizzy", "It's getting worse", "Repeat that", "Where is the helper?"].map((q) => <button key={q} disabled={busy} onClick={() => void say(q)} className="min-h-10 rounded-full border border-line px-3.5 text-sm">{q}</button>)}
              <button disabled={busy} onClick={() => void say("Help has arrived")} className="min-h-10 rounded-full bg-oksolid px-3.5 text-sm font-semibold text-white">Help has arrived</button>
            </div>
            {err && <Notice tone="danger" className="mt-3">{err}</Notice>}
            <form className="mt-3 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (t) { setText(""); void say(t); } }}>
              <button type="button" onClick={() => (listening ? l.current?.stop() : startListening())} disabled={!supported} aria-pressed={listening} aria-label={supported ? (listening ? "Stop listening" : "Talk to NEXA") : "Voice not supported"} className={cx("grid h-14 w-14 shrink-0 place-items-center rounded-full bg-dangersolid text-2xl text-white disabled:opacity-40", listening && "pulse-ring")}>🎙</button>
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? "Listening…" : "Type to NEXA…"} aria-label="Message to NEXA" maxLength={500} />
              <Button type="submit" disabled={!text.trim() || busy}>Send</Button>
            </form>
            <div className="mt-3"><Toggle checked={handsFree} onChange={setHandsFree} label="Hands-free" description="NEXA listens again after it speaks." /></div>
          </div>
        )}

        {markers.length > 0 && <div className="overflow-hidden rounded-2xl border border-line"><Map center={[markers[0].lat, markers[0].lng]} zoom={15} markers={markers} fitToMarkers className="h-60" label="Incident map" /></div>}

        {/* live incident state */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-2xl border border-line bg-surface p-4 text-sm sm:grid-cols-3">
          {[["Status", s.status], ["Situation", s.situation.replace(/_/g, " ")], ["Protocol", s.current_protocol ? `${s.current_protocol} v${s.protocol_version}` : "—"], ["Location shared", s.location_shared ? "Yes, with your helper" : "No"], ["Escalation level", String(s.escalation_level)], ["Emergency services", s.emergency_services_contacted ? "You contacted them" : s.emergency_services_advised ? "Advised: please call" : "—"]].map(([k, v]) => (
            <div key={k}><dt className="text-muted">{k}</dt><dd className="font-semibold">{v}</dd></div>
          ))}
        </dl>
        <p className="text-xs text-muted">{s.disclaimer}</p>

        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={async () => { try { setLog(await api<LogRow[]>(`/api/incidents/${iid}/log`)); } catch (e) { setErr(errorMessage(e)); } }}>View audit log</Button>
          {active && <Button variant="secondary" onClick={() => setEndOpen(true)}>End NEXA CARE</Button>}
        </div>
        {log && (
          <ul className="space-y-1 rounded-2xl bg-surface p-4 text-xs">
            {log.map((r) => <li key={r.id}><b>{r.kind}</b> <span className="text-muted">({r.actor}, {timeAgo(r.at)})</span> {r.content}</li>)}
          </ul>
        )}
      </div>

      <Modal open={endOpen} onClose={() => setEndOpen(false)} title="End NEXA CARE?">
        <p className="text-muted">If help hasn&apos;t arrived, your request stays open only if you choose &quot;I&apos;m safe now&quot;. Cancelling also cancels the alert to helpers.</p>
        <div className="mt-4 grid gap-2">
          <Button variant="success" onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/close`, { method: "POST", body: { resolution: "RESOLVED", reason: "user confirmed safe / help arrived" } })).then(() => setEndOpen(false))}>Help has arrived / I&apos;m safe</Button>
          <Button variant="danger" onClick={() => void call(() => api<CareReply>(`/api/incidents/${iid}/close`, { method: "POST", body: { resolution: "CANCELLED", reason: "user stopped care" } })).then(() => { setEndOpen(false); router.push("/"); })}>Cancel: false alarm</Button>
          <Button variant="secondary" onClick={() => setEndOpen(false)}>Keep NEXA CARE going</Button>
        </div>
      </Modal>
    </div>
  );
}
