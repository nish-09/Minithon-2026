"use client";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import Map from "@/components/Map";
import { Badge, Button, Card, type CardTone, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, Notice, SectionTitle, Select, Textarea, UrgencyBadge, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDuration, STATUS_LABEL, timeAgo } from "@/lib/format";
import { useQuery, useToast } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import type { Analytics, Dashboard, DirectoryItem, HelpRequest, IncidentState } from "@/lib/types";

const TABS = ["Overview", "Analytics", "Requests", "Incidents", "Users & Trust", "Reports", "Protocols", "Directory"] as const;
type Tab = (typeof TABS)[number];

export default function AdminPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("Overview");
  if (!user) return null;
  if (user.role !== "admin") return <ErrorState message="Administrator access is required." />;
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Admin</h1>
      <div role="tablist" aria-label="Admin sections" className="flex gap-1 overflow-x-auto rounded-xl bg-surface2 p-1">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cx("min-h-10 shrink-0 rounded-lg px-3.5 text-sm font-medium", tab === t ? "bg-surface shadow-sm" : "text-muted")}>{t}</button>
        ))}
      </div>
      <div role="tabpanel" aria-label={tab}>
        {tab === "Overview" && <Overview />}
        {tab === "Analytics" && <AnalyticsTab />}
        {tab === "Requests" && <RequestsTab />}
        {tab === "Incidents" && <IncidentsTab />}
        {tab === "Users & Trust" && <UsersTab />}
        {tab === "Reports" && <ReportsTab />}
        {tab === "Protocols" && <ProtocolsTab />}
        {tab === "Directory" && <DirectoryTab />}
      </div>
    </div>
  );
}

function Stat({ label, value, tone, card }: { label: string; value: string | number; tone?: "danger" | "warn"; card?: CardTone }) {
  return (
    <Card tone={card} className="!p-4">
      <p className="text-sm font-semibold text-ink">{label}</p>
      <p className={cx("mt-1 text-3xl font-bold tabular-nums", tone === "danger" && Number(value) > 0 && "text-danger", tone === "warn" && Number(value) > 0 && "text-warn")}>{value}</p>
    </Card>
  );
}

function Overview() {
  const d = useQuery(() => api<Dashboard>("/api/admin/dashboard"), []);
  const inc = useQuery(() => api<(IncidentState & { user_id: number; description: string })[]>("/api/admin/incidents?active_only=true"), []);
  useLiveEvents((e) => { if (e.type === "notification" || e.type === "request_update" || e.type === "incident_update") { void d.reload(); void inc.reload(); } });
  if (d.loading) return <LoadingBlock />;
  if (d.error || !d.data) return <ErrorState message={d.error ?? "No data"} onRetry={d.reload} />;
  const x = d.data;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Active requests" value={x.active_requests} />
        <Stat label="Urgent requests" value={x.urgent_requests} tone="warn" />
        <Stat label="Critical incidents" value={x.critical_incidents} tone="danger" card={x.critical_incidents > 0 ? "peach" : undefined} />
        <Stat label="Helpers online" value={x.helpers_online} card="lavender" />
        <Stat label="Unmatched requests" value={x.unmatched_requests} tone="warn" />
        <Stat label="Completed today" value={x.completed_today} card="mint" />
        <Stat label="Avg response time" value={fmtDuration(x.avg_response_seconds)} card="yellow" />
        <Stat label="Open reports" value={x.open_reports} tone="warn" />
      </div>
      <section>
        <SectionTitle>Active critical incidents</SectionTitle>
        {(inc.data ?? []).length === 0 ? <EmptyState icon={<CheckCircle2 size={26} />} title="No active incidents" /> : (
          <ul className="space-y-2">{inc.data!.map((i) => (
            <li key={i.id}><Card className="!p-4 border-danger/40">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">{i.incident_id} · {i.situation.replace(/_/g, " ")}</p><Badge tone="danger">Level {i.escalation_level}</Badge></div>
              <p className="text-sm text-muted">{i.protocol_title} · step {i.current_step}/{i.total_steps} · helper: {i.assigned_helper_name ?? "none yet"}{i.helper_eta_minutes ? ` (ETA ${Math.round(i.helper_eta_minutes)} min)` : ""}</p>
              {i.request_id && <Link className="text-sm font-semibold text-brandtext" href={`/requests/${i.request_id}`}>Open request →</Link>}
            </Card></li>
          ))}</ul>
        )}
      </section>
    </div>
  );
}

function Bars({ rows, label }: { rows: { label: string; value: number; extra?: string }[]; label: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure aria-label={label}>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[minmax(120px,190px)_1fr_auto] items-center gap-3 text-sm">
            <span className="leading-tight">{r.label}</span>
            <span className="h-3 rounded-full bg-surface2"><span className="block h-full rounded-full bg-brand" style={{ width: `${(r.value / max) * 100}%` }} /></span>
            <span className="tabular-nums font-semibold">{r.value}{r.extra ? <span className="ml-1 font-normal text-muted">{r.extra}</span> : null}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function AnalyticsTab() {
  const [days, setDays] = useState(30);
  const a = useQuery(() => api<Analytics>(`/api/admin/analytics?days=${days}`), [days]);
  if (a.loading) return <LoadingBlock />;
  if (a.error || !a.data) return <ErrorState message={a.error ?? "No data"} onRetry={a.reload} />;
  const x = a.data;
  const hm = x.heatmap;
  const center: [number, number] = hm.length ? [hm.reduce((s, h) => s + h.lat, 0) / hm.length, hm.reduce((s, h) => s + h.lng, 0) / hm.length] : [12.9352, 77.6245];
  return (
    <div className="space-y-5">
      <Field label="Period">{(id) => <Select id={id} value={days} onChange={(e) => setDays(Number(e.target.value))} className="max-w-48"><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></Select>}</Field>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Requests by category ({x.total_requests})</SectionTitle>
          {x.categories.length === 0 ? <p className="text-sm text-muted">No requests in this period.</p> : <Bars label="Requests by category" rows={x.categories.map((c) => ({ label: c.label, value: c.count, extra: c.unmatched ? `(${c.unmatched} unmatched)` : undefined }))} />}
        </Card>
        <Card>
          <SectionTitle>Response times</SectionTitle>
          <p className="text-sm">Median <b>{fmtDuration(x.response_time.median_s)}</b> · 90th percentile <b>{fmtDuration(x.response_time.p90_s)}</b> <span className="text-muted">({x.response_time.count} responses)</span></p>
          <p className="mt-3 text-sm">Urgent incidents: <b>{x.urgent_incidents}</b></p>
          <p className="mt-1 text-sm text-muted">By urgency: {Object.entries(x.urgency).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</p>
        </Card>
        <Card>
          <SectionTitle>Volunteer availability (by skill area)</SectionTitle>
          {Object.keys(x.volunteer_availability).length === 0 ? <p className="text-sm text-muted">No available volunteers.</p> : <Bars label="Available volunteers" rows={Object.entries(x.volunteer_availability).sort((p, q) => q[1] - p[1]).map(([k, v]) => ({ label: k.replace(/_/g, " "), value: v }))} />}
        </Card>
        <Card>
          <SectionTitle>Resource gaps</SectionTitle>
          {x.resource_gaps.length === 0 ? <p className="text-sm text-muted">No gaps detected: demand is covered by available helpers.</p> : (
            <ul className="space-y-2 text-sm">{x.resource_gaps.map((g) => <li key={g.category} className="flex justify-between gap-3"><span>{g.label}</span><span className="text-warn">{g.requests} requests · {g.available_helpers} helpers available</span></li>)}</ul>
          )}
        </Card>
      </div>
      <Card className="!p-2">
        <p className="px-3 pt-2 text-sm font-semibold">Community demand heatmap</p>
        <p className="px-3 pb-2 text-xs text-muted">Aggregated to about 1 km cells and weighted by urgency. No personal data.</p>
        <Map center={center} zoom={12} heat={hm.map((h) => ({ lat: h.lat, lng: h.lng, weight: h.weight, label: `${h.count} weighted requests` }))} className="h-80" label="Demand heatmap" />
      </Card>
      <details className="text-sm"><summary className="cursor-pointer text-muted">Table view of requests per day</summary>
        <table className="mt-2 w-full text-left"><thead><tr><th>Day</th><th>Requests</th></tr></thead><tbody>{x.requests_per_day.map(([d, n]) => <tr key={d}><td>{d}</td><td>{n}</td></tr>)}</tbody></table>
      </details>
    </div>
  );
}

function RequestsTab() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const r = useQuery(() => api<HelpRequest[]>(`/api/admin/requests${status ? `?status=${status}` : ""}`), [status]);
  return (
    <div className="space-y-3">
      <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-56"><option value="">All statuses</option>{Object.keys(STATUS_LABEL).map((s) => <option key={s} value={s}>{s}</option>)}</Select>
      {r.loading ? <LoadingBlock /> : r.error ? <ErrorState message={r.error} onRetry={r.reload} /> : (r.data ?? []).length === 0 ? <EmptyState title="No requests" /> : (
        <ul className="space-y-2">{r.data!.map((q) => (
          <li key={q.id}><Card className="!p-3"><div className="flex flex-wrap items-center gap-3">
            <span className="text-xl">{q.icon}</span>
            <div className="min-w-0 flex-1"><Link href={`/requests/${q.id}`} className="font-semibold hover:underline">#{q.id} {q.title}</Link><p className="text-xs text-muted">{STATUS_LABEL[q.status] ?? q.status} · {q.requester?.name} · {timeAgo(q.created_at)} · {q.recipients?.length ?? 0} asked</p></div>
            <UrgencyBadge urgency={q.urgency} />
            {!["COMPLETED", "RATED", "CANCELLED", "EXPIRED"].includes(q.status) && <Button size="sm" variant="secondary" onClick={async () => { try { await api(`/api/admin/requests/${q.id}/cancel`, { method: "POST" }); toast.push({ kind: "success", title: "Cancelled" }); void r.reload(); } catch (e) { toast.push({ kind: "error", title: "Failed", body: errorMessage(e) }); } }}>Cancel</Button>}
          </div></Card></li>
        ))}</ul>
      )}
    </div>
  );
}

function IncidentsTab() {
  const inc = useQuery(() => api<(IncidentState & { user_id: number; description: string })[]>("/api/admin/incidents"), []);
  const [log, setLog] = useState<{ id: string; rows: { id: number; kind: string; actor: string; content: string; at: string }[] } | null>(null);
  if (inc.loading) return <LoadingBlock />;
  if (inc.error) return <ErrorState message={inc.error} onRetry={inc.reload} />;
  return (
    <div className="space-y-3">
      {(inc.data ?? []).length === 0 ? <EmptyState title="No incidents yet" /> : inc.data!.map((i) => (
        <Card key={i.id} className="!p-4">
          <div className="flex flex-wrap items-center gap-2"><p className="font-semibold">{i.incident_id}</p><Badge tone={i.status === "ACTIVE" ? "danger" : "neutral"}>{i.status}</Badge><span className="text-sm text-muted">{i.situation.replace(/_/g, " ")} · {i.current_protocol} v{i.protocol_version}</span></div>
          <p className="mt-1 text-sm">{i.description}</p>
          <p className="text-xs text-muted">Escalation {i.escalation_level} · emergency services {i.emergency_services_contacted ? "contacted" : "advised"} · helper {i.assigned_helper_name ?? "—"}</p>
          <Button size="sm" variant="ghost" onClick={async () => setLog({ id: i.incident_id, rows: await api(`/api/incidents/${i.id}/log`) })}>Audit log</Button>
        </Card>
      ))}
      <Modal open={log !== null} onClose={() => setLog(null)} title={`Audit log ${log?.id ?? ""}`} wide>
        <ul className="space-y-1.5 text-sm">{log?.rows.map((r) => <li key={r.id}><b>{r.kind}</b> <span className="text-muted">({r.actor}, {timeAgo(r.at)})</span> {r.content}</li>)}</ul>
      </Modal>
    </div>
  );
}

interface AdminUser { id: number; name: string; email: string; role: string; is_active: boolean; identity_verified: boolean; trust_score: number | null; certifications: { slug: string; verified: boolean }[] }

function UsersTab() {
  const toast = useToast();
  const [q, setQ] = useState("");
  const users = useQuery(() => api<AdminUser[]>(`/api/admin/users?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}`), [q]);
  const review = useQuery(() => api<{ user_id: number; name: string; score: number; reasons: string[] }[]>("/api/admin/trust-review"), []);
  async function run(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); toast.push({ kind: "success", title: ok }); void users.reload(); void review.reload(); } catch (e) { toast.push({ kind: "error", title: "Failed", body: errorMessage(e) }); }
  }
  return (
    <div className="space-y-5">
      <section>
        <SectionTitle>Trust review queue</SectionTitle>
        {review.loading ? <LoadingBlock /> : (review.data ?? []).length === 0 ? <Notice tone="ok">No trust anomalies right now.</Notice> : (
          <ul className="space-y-2">{review.data!.map((f) => <li key={f.user_id}><Card className="!p-3"><p className="font-semibold">{f.name} <Badge tone="warn">score {f.score}</Badge></p><p className="text-sm text-muted">{f.reasons.join(" · ")}</p></Card></li>)}</ul>
        )}
      </section>
      <section>
        <SectionTitle>Users</SectionTitle>
        <Input aria-label="Search users" placeholder="Search name or email…" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3 max-w-sm" />
        {users.loading ? <LoadingBlock /> : users.error ? <ErrorState message={users.error} onRetry={users.reload} /> : (
          <ul className="space-y-2">{users.data!.map((u) => (
            <li key={u.id}><Card className="!p-3">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1"><Link href={`/users/${u.id}`} className="font-semibold hover:underline">{u.name}</Link> {u.role === "admin" && <Badge tone="brand">admin</Badge>} {!u.is_active && <Badge tone="danger">deactivated</Badge>}<p className="truncate text-xs text-muted">{u.email} · trust {u.trust_score ?? "—"}</p></div>
                <Button size="sm" variant="secondary" onClick={() => void run(() => api(`/api/admin/users/${u.id}/verify`, { method: "POST", body: { kind: "identity", approved: !u.identity_verified } }), u.identity_verified ? "Identity un-verified" : "Identity verified")}>{u.identity_verified ? "✓ Identity" : "Verify identity"}</Button>
                {u.role !== "admin" && <Button size="sm" variant={u.is_active ? "ghost" : "success"} className={u.is_active ? "text-danger" : ""} onClick={() => void run(() => api(`/api/admin/users/${u.id}/moderate`, { method: "PATCH", body: { is_active: !u.is_active } }), u.is_active ? "User deactivated" : "User reactivated")}>{u.is_active ? "Deactivate" : "Reactivate"}</Button>}
              </div>
              {u.certifications.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{u.certifications.map((c) => <button key={c.slug} onClick={() => void run(() => api(`/api/admin/users/${u.id}/certifications`, { method: "POST", body: { certification: c.slug, verified: !c.verified } }), c.verified ? "Certification revoked" : "Certification verified")} className="rounded-full"><Badge tone={c.verified ? "ok" : "warn"}>{c.verified ? "✓" : "?"} {c.slug.replace(/_/g, " ")}</Badge></button>)}</div>}
            </Card></li>
          ))}</ul>
        )}
      </section>
    </div>
  );
}

function ReportsTab() {
  const toast = useToast();
  const [st, setSt] = useState("OPEN");
  const r = useQuery(() => api<{ id: number; reporter_id: number; target_user_id: number | null; reason: string; details: string; status: string; created_at: string }[]>(`/api/admin/reports?status=${st}`), [st]);
  return (
    <div className="space-y-3">
      <Select aria-label="Status" value={st} onChange={(e) => setSt(e.target.value)} className="max-w-48"><option value="OPEN">Open</option><option value="UPHELD">Upheld</option><option value="DISMISSED">Dismissed</option></Select>
      {r.loading ? <LoadingBlock /> : r.error ? <ErrorState message={r.error} onRetry={r.reload} /> : (r.data ?? []).length === 0 ? <EmptyState icon={<CheckCircle2 size={26} />} title="Nothing here" /> : r.data!.map((x) => (
        <Card key={x.id} className="!p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold capitalize">{x.reason.replace("_", " ")} <span className="text-sm font-normal text-muted">about {x.target_user_id ? <Link className="underline" href={`/users/${x.target_user_id}`}>user #{x.target_user_id}</Link> : "a request"} · {timeAgo(x.created_at)}</span></p><Badge>{x.status}</Badge></div>
          {x.details && <p className="mt-1 text-sm">{x.details}</p>}
          {x.status === "OPEN" && <div className="mt-3 flex gap-2">
            {(["UPHELD", "DISMISSED"] as const).map((s) => <Button key={s} size="sm" variant={s === "UPHELD" ? "danger" : "secondary"} onClick={async () => { try { await api(`/api/admin/reports/${x.id}/resolve`, { method: "POST", body: { status: s } }); toast.push({ kind: "success", title: s === "UPHELD" ? "Report upheld; trust updated" : "Report dismissed" }); void r.reload(); } catch (e) { toast.push({ kind: "error", title: "Failed", body: errorMessage(e) }); } }}>{s === "UPHELD" ? "Uphold" : "Dismiss"}</Button>)}
          </div>}
        </Card>
      ))}
    </div>
  );
}

interface Proto { id: number; slug: string; version: number; title: string; is_active: boolean; keywords: string[]; requires_emergency_services: boolean; source: string; steps: { position: number; instruction: string; fallback_instruction: string | null; is_critical: boolean }[] }

function ProtocolsTab() {
  const toast = useToast();
  const p = useQuery(() => api<Proto[]>("/api/admin/protocols"), []);
  const [edit, setEdit] = useState<Proto | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="space-y-3">
      <Notice tone="warn">Protocols are the only source of medical guidance NEXA CARE can give. Publish changes as a new version after clinical review; the newest active version is used for new incidents, and earlier incidents keep the version they started with.</Notice>
      {p.loading ? <LoadingBlock /> : p.error ? <ErrorState message={p.error} onRetry={p.reload} /> : p.data!.map((x) => (
        <Card key={x.id} className="!p-4">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setOpen(open === x.id ? null : x.id)} aria-expanded={open === x.id} className="text-left font-semibold">{x.title}</button>
            <Badge>{x.slug} v{x.version}</Badge>
            <Badge tone={x.is_active ? "ok" : "neutral"}>{x.is_active ? "active" : "inactive"}</Badge>
            {x.requires_emergency_services && <Badge tone="danger">emergency first</Badge>}
            <span className="ml-auto flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setEdit(x)}>New version</Button>
              <Button size="sm" variant="ghost" onClick={async () => { try { await api(`/api/admin/protocols/${x.id}/active`, { method: "POST", body: { is_active: !x.is_active } }); void p.reload(); } catch (e) { toast.push({ kind: "error", title: "Failed", body: errorMessage(e) }); } }}>{x.is_active ? "Deactivate" : "Activate"}</Button>
            </span>
          </div>
          <p className="mt-1 text-xs text-muted">{x.source}</p>
          {open === x.id && <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm">{x.steps.map((s) => <li key={s.position}>{s.instruction}{s.is_critical && <Badge tone="danger" className="ml-2">critical</Badge>}{s.fallback_instruction && <p className="text-muted">If they can&apos;t: {s.fallback_instruction}</p>}</li>)}</ol>}
        </Card>
      ))}
      {edit && <ProtocolEditor base={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); void p.reload(); }} />}
    </div>
  );
}

function ProtocolEditor({ base, onClose, onSaved }: { base: Proto; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(base.title);
  const [keywords, setKeywords] = useState(base.keywords.join(", "));
  const [source, setSource] = useState("");
  const [emerg, setEmerg] = useState(base.requires_emergency_services);
  const [steps, setSteps] = useState(base.steps.map((s) => ({ instruction: s.instruction, fallback_instruction: s.fallback_instruction ?? "", is_critical: s.is_critical })));
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onClose={onClose} title={`New version of ${base.slug}`} wide>
      <div className="space-y-3">
        <Field label="Title">{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        <Field label="Trigger keywords (comma separated)">{(id) => <Input id={id} value={keywords} onChange={(e) => setKeywords(e.target.value)} />}</Field>
        <Field label="Source / reviewer" hint="Who reviewed this and against which guidance?">{(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} maxLength={200} />}</Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={emerg} onChange={(e) => setEmerg(e.target.checked)} /> Always lead with emergency services</label>
        {steps.map((s, i) => (
          <div key={i} className="space-y-2 rounded-xl border border-line p-3">
            <div className="flex items-center justify-between"><b className="text-sm">Step {i + 1}</b>{steps.length > 1 && <button className="text-xs text-danger underline" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>remove</button>}</div>
            <Textarea aria-label={`Step ${i + 1} instruction`} rows={2} value={s.instruction} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, instruction: e.target.value } : x))} />
            <Input aria-label={`Step ${i + 1} fallback`} placeholder="If the person can't do this…" value={s.fallback_instruction} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, fallback_instruction: e.target.value } : x))} />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={s.is_critical} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, is_critical: e.target.checked } : x))} /> Critical step</label>
          </div>
        ))}
        <Button variant="secondary" onClick={() => setSteps([...steps, { instruction: "", fallback_instruction: "", is_critical: false }])}>+ Add step</Button>
        <Button className="w-full" loading={busy} disabled={steps.some((s) => s.instruction.trim().length < 3)} onClick={async () => {
          setBusy(true);
          try {
            await api("/api/admin/protocols", { method: "POST", body: { slug: base.slug, title, situation_keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean), requires_emergency_services: emerg, source, steps: steps.map((s) => ({ instruction: s.instruction.trim(), fallback_instruction: s.fallback_instruction.trim() || null, is_critical: s.is_critical })) } });
            toast.push({ kind: "success", title: "New version published" });
            onSaved();
          } catch (e) { toast.push({ kind: "error", title: "Couldn't publish", body: errorMessage(e) }); } finally { setBusy(false); }
        }}>Publish new version</Button>
      </div>
    </Modal>
  );
}

function DirectoryTab() {
  const toast = useToast();
  const d = useQuery(() => api<DirectoryItem[]>("/api/directory?radius_km=100"), []);
  const [f, setF] = useState({ name: "", category: "pharmacy", phone: "" });
  async function add(e: React.FormEvent) {
    e.preventDefault();
    try { await api("/api/admin/directory", { method: "POST", body: { name: f.name, category: f.category, phone: f.phone || null } }); setF({ ...f, name: "", phone: "" }); toast.push({ kind: "success", title: "Added" }); void d.reload(); }
    catch (err) { toast.push({ kind: "error", title: "Couldn't add", body: errorMessage(err) }); }
  }
  return (
    <div className="space-y-4">
      <Card>
        <form onSubmit={add} className="flex flex-wrap items-end gap-3">
          <Field label="Name">{(id) => <Input id={id} required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
          <Field label="Category">{(id) => <Select id={id} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["emergency", "hospital", "pharmacy", "plumber", "electrician", "tutor", "pet", "volunteer", "other"].map((c) => <option key={c}>{c}</option>)}</Select>}</Field>
          <Field label="Phone">{(id) => <Input id={id} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />}</Field>
          <Button type="submit">Add entry</Button>
        </form>
      </Card>
      {d.loading ? <LoadingBlock /> : d.error ? <ErrorState message={d.error} onRetry={d.reload} /> : (
        <ul className="space-y-2">{d.data!.map((e) => <li key={e.id}><Card className="!p-3 flex items-center gap-3"><Badge>{e.category}</Badge><span className="flex-1">{e.name} <span className="text-sm text-muted">{e.phone}</span></span><button className="text-sm text-danger underline" onClick={async () => { try { await api(`/api/admin/directory/${e.id}`, { method: "DELETE" }); void d.reload(); } catch (err) { toast.push({ kind: "error", title: "Failed", body: errorMessage(err) }); } }}>Delete</button></Card></li>)}</ul>
      )}
    </div>
  );
}
