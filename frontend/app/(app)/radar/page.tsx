"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import Map, { type MapMarker } from "@/components/Map";
import { Badge, Button, Card, ErrorState, Field, LoadingBlock, Notice, Select, Toggle, UrgencyBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDistance, timeAgo } from "@/lib/format";
import { SAMPLE_LOCATION, useLocation, useQuery } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import type { CommunityEventItem, DirectoryItem, HelperMarker, RadarItem, Reference } from "@/lib/types";

const URG_COLOR = { normal: "#4f46e5", urgent: "#d97706", critical: "#dc2626" } as const;

export default function RadarPage() {
  const { user } = useAuth();
  const loc = useLocation();
  const ref = useQuery(() => api<Reference>("/api/reference"), []);
  const [category, setCategory] = useState("");
  const [urgency, setUrgency] = useState("");
  const [skill, setSkill] = useState("");
  const [radius, setRadius] = useState(10);
  const [minTrust, setMinTrust] = useState(0);
  const [layers, setLayers] = useState({ requests: true, helpers: true, events: true, services: false });

  const c = loc.coords;
  const qs = c ? `lat=${c.lat}&lng=${c.lng}&radius_km=${radius}` : "";
  const reqs = useQuery(c ? () => api<RadarItem[]>(`/api/requests/radar?${qs}${category ? `&category=${category}` : ""}${urgency ? `&urgency=${urgency}` : ""}`) : null, [qs, category, urgency]);
  const helpers = useQuery(c ? () => api<HelperMarker[]>(`/api/helpers/nearby?${qs}${skill ? `&skill=${skill}` : ""}&min_trust=${minTrust}`) : null, [qs, skill, minTrust]);
  const events = useQuery(c ? () => api<CommunityEventItem[]>(`/api/events?${qs}`) : null, [qs]);
  const services = useQuery(c && layers.services ? () => api<DirectoryItem[]>(`/api/directory?${qs}`) : null, [qs, layers.services]);

  useLiveEvents((e) => {
    if (e.type === "request_update" || e.type === "notification") { void reqs.reload(); void helpers.reload(); }
  });

  const markers = useMemo<MapMarker[]>(() => {
    const m: MapMarker[] = [];
    if (c) m.push({ id: "me", lat: c.lat, lng: c.lng, emoji: "📍", color: "#0f172a", label: "You" });
    if (layers.requests) for (const r of reqs.data ?? []) m.push({ id: `r${r.id}`, lat: r.lat, lng: r.lng, emoji: r.icon, color: URG_COLOR[r.urgency], label: r.label, detail: `${r.urgency} · ${fmtDistance(r.distance_km)} · approximate area`, pulse: r.urgency === "critical" });
    if (layers.helpers) for (const h of helpers.data ?? []) m.push({ id: `h${h.id}`, lat: h.lat, lng: h.lng, emoji: "🧑‍🤝‍🧑", color: "#16a34a", label: h.verified ? "Verified helper" : "Helper", detail: `${fmtDistance(h.distance_km)}${h.trust_score != null ? ` · trust ${Math.round(h.trust_score)}` : ""}${h.skills.length ? ` · ${h.skills.join(", ").replace(/_/g, " ")}` : ""}` });
    if (layers.events) for (const e of events.data ?? []) m.push({ id: `e${e.id}`, lat: e.lat, lng: e.lng, emoji: "🎉", color: "#9333ea", label: e.title, detail: new Date(e.starts_at).toLocaleString() });
    if (layers.services) for (const s of (services.data ?? []).filter((x) => x.lat != null)) m.push({ id: `s${s.id}`, lat: s.lat!, lng: s.lng!, emoji: s.category === "hospital" ? "🏥" : s.category === "pharmacy" ? "💊" : "🔧", color: "#0891b2", label: s.name, detail: s.phone ?? undefined });
    return m;
  }, [c, layers, reqs.data, helpers.data, events.data, services.data]);

  if (!user) return null;
  const err = reqs.error || helpers.error;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Neighborhood Help Radar</h1>
        <p className="text-muted">What&apos;s happening near you. Locations are approximate and no names are shown.</p>
      </div>

      {!c ? (
        <Notice tone="warn">
          <p className="font-semibold">Share your location to see the radar.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={loc.request} loading={loc.status === "asking"}>Use my location</Button>
            <Button size="sm" variant="secondary" onClick={() => void loc.useSample()}>Use sample location ({SAMPLE_LOCATION.label})</Button>
          </div>
        </Notice>
      ) : (
        <>
          <Card className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Field label="Category">{(id) => <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All</option>{ref.data?.categories.map((x) => <option key={x.slug} value={x.slug}>{x.icon} {x.label}</option>)}</Select>}</Field>
            <Field label="Urgency">{(id) => <Select id={id} value={urgency} onChange={(e) => setUrgency(e.target.value)}><option value="">Any</option><option value="normal">Normal</option><option value="urgent">Urgent</option><option value="critical">Critical</option></Select>}</Field>
            <Field label="Helper skill">{(id) => <Select id={id} value={skill} onChange={(e) => setSkill(e.target.value)}><option value="">Any</option>{ref.data?.skills.map((x) => <option key={x.slug} value={x.slug}>{x.label}</option>)}</Select>}</Field>
            <Field label={`Distance: ${radius} km`}>{(id) => <input id={id} type="range" min={1} max={30} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="h-11 w-full accent-[var(--brand)]" />}</Field>
            <Field label={`Min. trust: ${minTrust}`}>{(id) => <input id={id} type="range" min={0} max={90} step={5} value={minTrust} onChange={(e) => setMinTrust(Number(e.target.value))} className="h-11 w-full accent-[var(--brand)]" />}</Field>
          </Card>
          <Card className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Toggle checked={layers.requests} onChange={(v) => setLayers((l) => ({ ...l, requests: v }))} label="Requests" />
            <Toggle checked={layers.helpers} onChange={(v) => setLayers((l) => ({ ...l, helpers: v }))} label="Available helpers" />
            <Toggle checked={layers.events} onChange={(v) => setLayers((l) => ({ ...l, events: v }))} label="Community activities" />
            <Toggle checked={layers.services} onChange={(v) => setLayers((l) => ({ ...l, services: v }))} label="Local services" />
          </Card>

          {err ? <ErrorState message={err} onRetry={() => { void reqs.reload(); void helpers.reload(); }} /> : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="overflow-hidden rounded-2xl border border-line">
                <Map center={[c.lat, c.lng]} zoom={radius > 15 ? 11 : radius > 6 ? 12 : 13} markers={markers} radiusKm={radius} className="h-[60vh] min-h-[360px]" label="Help radar map" />
              </div>
              <div className="space-y-3">
                <Card>
                  <p className="text-sm text-muted">In view</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <Badge tone="brand">{reqs.data?.length ?? 0} requests</Badge>
                    <Badge tone="ok">{helpers.data?.length ?? 0} helpers</Badge>
                    <Badge>{events.data?.length ?? 0} activities</Badge>
                  </div>
                </Card>
                {reqs.loading ? <LoadingBlock /> : (reqs.data ?? []).length === 0 ? (
                  <Card><p className="text-center text-sm text-muted">No open requests nearby{category || urgency ? " for these filters" : ""}. 🌿</p></Card>
                ) : (
                  <ul className="space-y-2">
                    {reqs.data!.slice(0, 12).map((r) => (
                      <li key={r.id}>
                        <Card className="!p-3">
                          <div className="flex items-center gap-3">
                            <span className="text-2xl" aria-hidden>{r.icon}</span>
                            <div className="min-w-0 flex-1"><p className="truncate font-medium">{r.label}</p><p className="text-xs text-muted">{fmtDistance(r.distance_km)} · {timeAgo(r.created_at)}</p></div>
                            <UrgencyBadge urgency={r.urgency} />
                          </div>
                          {r.invited && <Link href={`/requests/${r.id}`} className="mt-2 block text-sm font-semibold text-brandtext">You were asked to help →</Link>}
                        </Card>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
