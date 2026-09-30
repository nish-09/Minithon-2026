"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { ReportModal } from "@/components/ReportModal";
import Map, { type MapMarker } from "@/components/Map";
import { InviteCard } from "@/components/RequestCards";
import { StatusTimeline } from "@/components/StatusTimeline";
import { TrustCardModal, TrustChip } from "@/components/TrustCard";
import { Avatar, Badge, Button, Card, ErrorState, Field, Input, LoadingBlock, Modal, Notice, ProgressBar, SectionTitle, Textarea, UrgencyBadge, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { CLOSED_STATUSES, STATUS_LABEL, fmtCountdown, fmtDistance, fmtEta } from "@/lib/format";
import { useQuery, useToast } from "@/lib/hooks";
import { useLiveEvents, useRealtime } from "@/lib/realtime";
import type { HelpRequest, MatchResult } from "@/lib/types";

export default function RequestPage() {
  const { id } = useParams<{ id: string }>();
  const rid = Number(id);
  const router = useRouter();
  const toast = useToast();
  const { connected } = useRealtime();
  const { data: req, error, loading, reload } = useQuery(() => api<HelpRequest>(`/api/requests/${rid}`), [rid]);
  const [trustFor, setTrustFor] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [cancelOpen, setCancelOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  useLiveEvents((e) => {
    if ((e.type === "request_update" && e.request_id === rid) || (e.type === "notification" && e.data?.request_id === rid)) void reload();
  }, [rid]);

  // fallback polling when the socket is down, plus a 1s ticker for the circle countdown
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    const p = setInterval(() => !connected && void reload(), 10000);
    return () => {
      clearInterval(t);
      clearInterval(p);
    };
  }, [connected, reload]);

  const deadline = req?.circle_deadline ? new Date(req.circle_deadline).getTime() : null;
  const remaining = deadline ? deadline - now : null;
  useEffect(() => {
    if (req?.status === "TRUSTED_CIRCLE" && remaining !== null && remaining <= 0) {
      const t = setTimeout(() => void reload(), 1500); // server escalates on read
      return () => clearTimeout(t);
    }
  }, [req?.status, remaining, reload]);

  async function act(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key);
    try {
      await fn();
      if (ok) toast.push({ kind: "success", title: ok });
      await reload();
    } catch (e) {
      toast.push({ kind: "error", title: "That didn't work", body: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  const markers = useMemo<MapMarker[]>(() => {
    if (!req || req.lat == null || req.lng == null) return [];
    const m: MapMarker[] = [{ id: "req", lat: req.lat, lng: req.lng, emoji: req.viewer_role === "requester" ? "📍" : req.icon, color: req.urgency === "critical" ? "#dc2626" : "#4f46e5", label: req.viewer_role === "requester" ? "You" : req.location_approximate ? "Approximate location" : "Requester", pulse: req.urgency === "critical" }];
    for (const a of req.assignments ?? []) if (a.lat != null && a.lng != null) m.push({ id: `a${a.id}`, lat: a.lat, lng: a.lng, emoji: "🧑‍🤝‍🧑", color: "#16a34a", label: a.helper.name, detail: a.eta_minutes ? `ETA ${fmtEta(a.eta_minutes)}` : undefined });
    return m;
  }, [req]);

  if (loading) return <LoadingBlock />;
  if (error || !req) return <ErrorState message={error ?? "Request not found"} onRetry={reload} />;

  const role = req.viewer_role;
  const closed = CLOSED_STATUSES.includes(req.status);
  const open = ["CREATED", "ANALYZING", "MATCHING", "TRUSTED_CIRCLE", "HELPERS_NOTIFIED", "ESCALATED"].includes(req.status);
  const isRequester = role === "requester" || role === "admin";
  const critical = req.urgency === "critical";

  return (
    <div className={cx("space-y-5", critical && !closed && "")}>
      <div className="flex items-start gap-3">
        <button onClick={() => router.back()} className="mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-full hover:bg-surface2" aria-label="Back">←</button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-2xl" aria-hidden>{req.icon}</span>
            <h1 className="text-2xl font-bold tracking-tight">{req.title}</h1>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <UrgencyBadge urgency={req.urgency} />
            <Badge tone={closed ? "neutral" : "brand"}>{STATUS_LABEL[req.status] ?? req.status}</Badge>
            <span className="text-sm text-muted">{req.category_label}{req.time_requirement ? ` · ${req.time_requirement}` : ""}</span>
          </div>
        </div>
      </div>

      {critical && req.incident_id && isRequester && !closed && (
        <Link href={`/care/${req.incident_id}`} className="block rounded-2xl bg-dangersolid p-4 text-center font-bold text-white">
          🚨 Open NEXA CARE (voice guidance)
        </Link>
      )}

      {/* recipient: someone asked me */}
      {role === "recipient" && <InviteCard r={req} onChanged={reload} />}

      <Card>
        <StatusTimeline req={req} />
        {req.status === "TRUSTED_CIRCLE" && isRequester && (
          <div className="mt-4 rounded-xl bg-brandsoft p-4" role="status">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-semibold">Waiting for your Trusted Circle</p>
                <p className="text-sm text-muted">If nobody accepts in time, I&apos;ll find a nearby community helper automatically.</p>
              </div>
              {remaining !== null && <p className="text-2xl font-bold tabular-nums" aria-label="Time remaining">{fmtCountdown(remaining)}</p>}
            </div>
            <ul className="mt-3 space-y-1.5 text-sm">
              {(req.recipients ?? []).filter((r) => r.channel === "circle").map((r) => (
                <li key={r.user_id} className="flex items-center justify-between">
                  <span>{r.name ?? "Trusted contact"}</span>
                  <Badge tone={r.state === "ACCEPTED" ? "ok" : r.state === "DECLINED" ? "danger" : "neutral"}>{r.state === "NOTIFIED" ? "Waiting" : r.state.toLowerCase()}</Badge>
                </li>
              ))}
            </ul>
            <Button variant="secondary" size="sm" className="mt-3" loading={busy === "expand"} onClick={() => void act("expand", () => api(`/api/requests/${rid}/expand-to-community`, { method: "POST" }), "Looking for community help")}>
              Find community help now
            </Button>
          </div>
        )}
        {(req.status === "HELPERS_NOTIFIED" || req.status === "MATCHING" || req.status === "ESCALATED") && isRequester && (
          <div className="mt-4 flex items-center justify-between rounded-xl bg-surface2 p-4 text-sm" role="status">
            <span>
              {req.status === "MATCHING" ? "Still looking for someone suitable. I'll keep widening the search." : `${(req.recipients ?? []).filter((r) => r.state === "NOTIFIED").length} helper(s) notified. First suitable acceptance wins.`}
            </span>
            <span className="text-muted">Expires {req.expires_at ? new Date(req.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}</span>
          </div>
        )}
        {req.status === "EXPIRED" && isRequester && <Notice tone="warn" className="mt-4">No helper was found in time. You can post the request again or widen who you ask.</Notice>}
      </Card>

      {/* assigned helpers */}
      {isRequester && (req.assignments ?? []).length > 0 && (
        <section aria-label="Your helpers">
          <SectionTitle>{(req.assignments ?? []).length > 1 ? "Your helpers" : "Your helper"}</SectionTitle>
          <div className="space-y-3">
            {req.assignments!.map((a) => (
              <Card key={a.id}>
                <div className="flex items-center gap-3">
                  <Avatar name={a.helper.name} src={a.helper.avatar_url} size={52} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-lg font-semibold">{a.helper.name}</p>
                      <TrustChip score={a.helper.trust_score} onClick={() => setTrustFor(a.helper.id)} />
                    </div>
                    <p className="text-sm text-muted">{a.relationship_label}{a.helper.certifications.length ? ` · ${a.helper.certifications.join(", ")}` : ""}</p>
                  </div>
                  <div className="text-right">
                    {a.status === "ARRIVED" ? <Badge tone="ok">Arrived</Badge> : a.eta_minutes != null ? <><p className="text-2xl font-bold tabular-nums">{fmtEta(a.eta_minutes)}</p><p className="text-xs text-muted">{fmtDistance(a.distance_km)} away</p></> : null}
                  </div>
                </div>
                {a.status === "ACTIVE" && !closed && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button variant="ghost" size="sm" onClick={() => void act(`ns${a.id}`, () => api(`/api/requests/${rid}/no-show`, { method: "POST", body: { helper_id: a.helper.id } }), "No-show recorded. Finding someone else.")}>Didn&apos;t show up</Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        </section>
      )}

      {markers.length > 0 && (
        <Card className="!p-2">
          <Map center={[markers[0].lat, markers[0].lng]} zoom={15} markers={markers} fitToMarkers className="h-72" label="Request map" />
          {req.location_approximate && <p className="px-3 pb-2 pt-1 text-xs text-muted">Approximate location (about 1 km). Exact location is shared only with the person who accepts.</p>}
        </Card>
      )}

      {/* helper controls */}
      {role === "helper" && req.my_assignment && !closed && (
        <Card>
          <SectionTitle>You&apos;re helping {req.requester?.name}</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {req.status === "ACCEPTED" && <Button loading={busy === "otw"} onClick={() => void act("otw", () => api(`/api/requests/${rid}/progress`, { method: "POST", body: { status: "ON_THE_WAY" } }), "Requester notified")}>🚶 I&apos;m on my way</Button>}
            {["ACCEPTED", "ON_THE_WAY"].includes(req.status) && <Button variant="success" loading={busy === "arr"} onClick={() => void act("arr", () => api(`/api/requests/${rid}/progress`, { method: "POST", body: { status: "IN_PROGRESS" } }), "Marked as arrived")}>📍 I&apos;ve arrived</Button>}
            <Button variant="secondary" loading={busy === "wd"} onClick={() => void act("wd", () => api(`/api/requests/${rid}/withdraw`, { method: "POST" }), "You've withdrawn")}>I can&apos;t make it</Button>
          </div>
          {req.my_assignment.eta_minutes != null && <p className="mt-2 text-sm text-muted">Your ETA: {fmtEta(req.my_assignment.eta_minutes)} ({fmtDistance(req.my_assignment.distance_km)})</p>}
        </Card>
      )}

      {/* smartmatch */}
      {isRequester && open && <MatchList rid={rid} onInvited={reload} />}

      {/* complete / rate */}
      {isRequester && ["ACCEPTED", "ON_THE_WAY", "IN_PROGRESS"].includes(req.status) && (
        <Button size="lg" variant="success" className="w-full" loading={busy === "complete"} onClick={() => void act("complete", () => api(`/api/requests/${rid}/complete`, { method: "POST" }), "Marked complete. Credits exchanged.")}>
          ✓ Mark as complete
        </Button>
      )}
      {isRequester && ["COMPLETED", "RATED"].includes(req.status) && <RatePanel req={req} onDone={reload} />}

      {(req.assignments?.length ?? 0) > 0 || role === "helper" ? <ChatPanel requestId={rid} disabled={closed && req.status !== "COMPLETED"} /> : null}

      {isRequester && !closed && (
        <div className="flex flex-wrap gap-2">
          {open && <Button variant="secondary" onClick={() => setEditOpen(true)}>Edit request</Button>}
          {open && <AskCircleButton rid={rid} onDone={reload} />}
          <Button variant="ghost" className="text-danger" onClick={() => setCancelOpen(true)}>Cancel request</Button>
        </div>
      )}

      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel this request?">
        <p className="text-muted">Helpers who were asked will be told it&apos;s no longer needed.</p>
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={() => setCancelOpen(false)}>Keep it</Button>
          <Button variant="danger" className="flex-1" loading={busy === "cancel"} onClick={() => void act("cancel", () => api(`/api/requests/${rid}/cancel`, { method: "POST" }), "Request cancelled").then(() => setCancelOpen(false))}>Cancel request</Button>
        </div>
      </Modal>
      {editOpen && <EditModal req={req} onClose={() => setEditOpen(false)} onSaved={() => { setEditOpen(false); void reload(); }} />}
      <TrustCardModal userId={trustFor} onClose={() => setTrustFor(null)} />
    </div>
  );
}

function AskCircleButton({ rid, onDone }: { rid: number; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button variant="secondary" loading={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await api<{ asked: number }>(`/api/requests/${rid}/trusted-circle`, { method: "POST" });
        toast.push({ kind: "success", title: `Asked ${r.asked} trusted contact${r.asked === 1 ? "" : "s"}` });
        onDone();
      } catch (e) {
        toast.push({ kind: "info", title: "Trusted Circle", body: errorMessage(e) });
      } finally {
        setBusy(false);
      }
    }}>
      Also ask my Trusted Circle
    </Button>
  );
}

function MatchList({ rid, onInvited }: { rid: number; onInvited: () => void }) {
  const toast = useToast();
  const { data, error, loading, reload } = useQuery(() => api<{ matches: MatchResult[] }>(`/api/matching/${rid}?limit=6`), [rid]);
  const [trustFor, setTrustFor] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  useLiveEvents((e) => { if (e.type === "request_update" && e.request_id === rid) void reload(); }, [rid]);

  return (
    <section aria-label="SmartMatch recommendations">
      <SectionTitle action={<button onClick={reload} className="text-sm font-semibold text-brandtext">Refresh</button>}>SmartMatch suggestions</SectionTitle>
      {loading ? <LoadingBlock label="Ranking helpers…" /> : error ? <ErrorState message={error} onRetry={reload} /> : data!.matches.length === 0 ? (
        <Notice tone="warn">No suitable helpers are available right now. NEXA keeps widening the search.</Notice>
      ) : (
        <div className="space-y-3">
          {data!.matches.map((m, i) => (
            <Card key={m.helper.id} as="article">
              <div className="flex items-center gap-3">
                <Avatar name={m.helper.name} src={m.helper.avatar_url} size={44} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{i === 0 ? "Best match · " : ""}{m.in_circle ? m.helper.name : m.relationship_label}</p>
                    {m.in_circle && <Badge tone="brand">{m.relationship_label}</Badge>}
                    <TrustChip score={m.trust_score} onClick={() => setTrustFor(m.helper.id)} />
                  </div>
                  <p className="text-sm text-muted">{fmtDistance(m.distance_km)} · ETA {fmtEta(m.eta_minutes)}</p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold tabular-nums">{Math.round(m.match_score)}</p>
                  <p className="text-[11px] text-muted">match</p>
                </div>
              </div>
              <ul className="mt-2 flex flex-wrap gap-1.5">{m.reasons.map((r) => <Badge key={r}>{r}</Badge>)}</ul>
              <div className="mt-3 flex gap-2">
                <Button size="sm" loading={busy === m.helper.id} onClick={async () => {
                  setBusy(m.helper.id);
                  try { await api(`/api/matching/${rid}/invite/${m.helper.id}`, { method: "POST" }); toast.push({ kind: "success", title: "Asked for help" }); onInvited(); void reload(); }
                  catch (e) { toast.push({ kind: "info", title: "Already asked or unavailable", body: errorMessage(e) }); }
                  finally { setBusy(null); }
                }}>Ask {m.in_circle ? m.helper.name.split(" ")[0] : "this helper"}</Button>
                <Button size="sm" variant="ghost" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>Why this match?</Button>
              </div>
              {open === i && (
                <div className="mt-3 space-y-2 rounded-xl bg-surface2 p-3 text-sm">
                  <p className="text-muted">Match score is how suitable they are for <b>this</b> request right now. Trust score ({Math.round(m.trust_score)}) is how reliable they are in general{m.category_trust != null ? `; in this category ${Math.round(m.category_trust)}` : ""}.</p>
                  {Object.entries(m.breakdown).map(([k, v]) => (
                    <div key={k}><div className="flex justify-between capitalize"><span>{k}</span><span className="tabular-nums">{Math.round(v)}</span></div><ProgressBar value={v} label={k} /></div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
      <TrustCardModal userId={trustFor} onClose={() => setTrustFor(null)} />
    </section>
  );
}

function RatePanel({ req, onDone }: { req: HelpRequest; onDone: () => void }) {
  const toast = useToast();
  const done = new Set((req.reviews ?? []).map((r) => r.helper_id));
  const todo = (req.assignments ?? []).filter((a) => a.status === "DONE" && !done.has(a.helper.id));
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportFor, setReportFor] = useState<number | null>(null);
  if (todo.length === 0) return <Notice tone="ok">Thank you for rating your helper{(req.assignments?.length ?? 0) > 1 ? "s" : ""}. Your feedback shapes their Trust Card.</Notice>;
  const a = todo[0];
  return (
    <Card>
      <SectionTitle>How was {a.helper.name}?</SectionTitle>
      <div className="flex gap-1" role="radiogroup" aria-label="Rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} role="radio" aria-checked={rating === n} aria-label={`${n} star${n > 1 ? "s" : ""}`} onClick={() => setRating(n)} className={cx("h-12 w-12 rounded-xl text-2xl", n <= rating ? "text-warn" : "text-line")}>★</button>
        ))}
      </div>
      <Field label="Comment (optional)">{(id) => <Textarea id={id} rows={3} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
      <div className="mt-3 flex gap-2">
        <Button loading={busy} onClick={async () => {
          setBusy(true);
          try { await api(`/api/requests/${req.id}/review`, { method: "POST", body: { helper_id: a.helper.id, rating, comment } }); toast.push({ kind: "success", title: "Thanks for your feedback" }); setComment(""); onDone(); }
          catch (e) { toast.push({ kind: "error", title: "Couldn't save rating", body: errorMessage(e) }); }
          finally { setBusy(false); }
        }}>Submit rating</Button>
        <Button variant="ghost" onClick={() => setReportFor(a.helper.id)}>Report a problem</Button>
      </div>
      <ReportModal userId={reportFor} requestId={req.id} onClose={() => setReportFor(null)} />
    </Card>
  );
}

function EditModal({ req, onClose, onSaved }: { req: HelpRequest; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(req.title);
  const [description, setDescription] = useState(req.description);
  const [n, setN] = useState(req.num_helpers);
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title="Edit request">
      <div className="space-y-3">
        <Field label="Title">{(id) => <Input id={id} value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} />}</Field>
        <Field label="Details">{(id) => <Textarea id={id} rows={3} value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <Field label="People needed">{(id) => <Input id={id} type="number" min={Math.max(1, req.filled_slots)} max={20} value={n} onChange={(e) => setN(Number(e.target.value) || 1)} />}</Field>
        <Button className="w-full" loading={busy} disabled={title.trim().length < 2} onClick={async () => {
          setBusy(true);
          try { await api(`/api/requests/${req.id}`, { method: "PATCH", body: { title, description, num_helpers: n } }); onSaved(); }
          catch (e) { toast.push({ kind: "error", title: "Couldn't save", body: errorMessage(e) }); }
          finally { setBusy(false); }
        }}>Save changes</Button>
      </div>
    </Modal>
  );
}
