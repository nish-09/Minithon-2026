"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { MicButton } from "@/components/MicButton";
import { Badge, Button, Card, Field, Input, LoadingBlock, Notice, Segmented, Select, Textarea, Toggle, UrgencyBadge, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtCountdown, fmtDistance } from "@/lib/format";
import { SAMPLE_LOCATION, useLocation, useQuery, useToast } from "@/lib/hooks";
import type { HelperMarker, Reference, Understanding, UnderstandResponse, Urgency } from "@/lib/types";

type Routing = "circle_first" | "community" | "custom";

function NewRequest() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const loc = useLocation();
  const ref = useQuery(() => api<Reference>("/api/reference"), []);

  const [text, setText] = useState(() => params.get("text") ?? (params.get("category") ? `I need help with ${params.get("category")!.replace(/_/g, " ")}: ` : ""));
  const [interim, setInterim] = useState("");
  const [step, setStep] = useState<"describe" | "review">("describe");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<UnderstandResponse | null>(null);
  const [u, setU] = useState<Understanding | null>(null);
  const [routing, setRouting] = useState<Routing>("circle_first");
  const [custom, setCustom] = useState<Set<number>>(new Set());
  const [share, setShare] = useState(true);
  const [reveal, setReveal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [helpers, setHelpers] = useState<HelperMarker[]>([]);

  const coords = loc.coords;

  async function understand() {
    setError(null);
    if (text.trim().length < 3) return setError("Tell me a little more about what you need.");
    if (!coords) return setError("Share your location first so I can find people near you.");
    setChecking(true);
    try {
      const r = await api<UnderstandResponse>("/api/ai/understand-request", { method: "POST", body: { text: text.trim(), lat: coords.lat, lng: coords.lng } });
      setRes(r);
      setU(r.understanding);
      const pref = user?.privacy.trusted_circle_default_mode;
      setRouting(params.get("mode") === "custom" ? "custom" : r.trusted_circle.count === 0 ? "community" : pref === "community" ? "community" : "circle_first");
      setReveal(user?.privacy.reveal_relationship_to_helpers ?? false);
      setStep("review");
      if (r.understanding.urgency !== "critical") {
        api<HelperMarker[]>(`/api/helpers/nearby?lat=${coords.lat}&lng=${coords.lng}&radius_km=10`).then(setHelpers).catch(() => setHelpers([]));
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  }

  // arriving with ?text= (from Home) goes straight to review once the location is known
  const auto = useRef(false);
  useEffect(() => {
    if (!auto.current && params.get("text") && coords && step === "describe") {
      auto.current = true;
      void understand();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coords]);

  const critical = u?.urgency === "critical";
  const urgentish = u?.urgency === "urgent";
  const catLabel = useMemo(() => ref.data?.categories.find((c) => c.slug === u?.category), [ref.data, u?.category]);
  const windowS = res?.circle_window_s ?? 0;

  async function submit() {
    if (!u || !coords) return;
    setSubmitting(true);
    setError(null);
    try {
      if (critical) {
        const r = await api<{ incident: { id: number } }>("/api/incidents", { method: "POST", body: { text: text.trim(), lat: coords.lat, lng: coords.lng, share_location: share } });
        router.replace(`/care/${r.incident.id}`);
        return;
      }
      const body: Record<string, unknown> = {
        text: text.trim(), lat: coords.lat, lng: coords.lng, share_location: share, reveal_relationship: routing !== "community" && reveal,
        routing_mode: urgentish && routing === "circle_first" ? "circle_first" : routing,
        overrides: { category: u.category, urgency: u.urgency, num_helpers: u.num_helpers, title: u.title, ...(u.time_requirement ? { time_requirement: u.time_requirement } : {}) },
      };
      if (routing === "custom") body.custom_recipient_ids = [...custom];
      const r = await api<{ id: number }>("/api/requests", { method: "POST", body });
      toast.push({ kind: "success", title: "Request sent", body: routing === "circle_first" ? "Asking your Trusted Circle first." : "Finding someone nearby." });
      router.replace(`/requests/${r.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (!user) return null;

  /* ------------------ step 1 ------------------ */
  if (step === "describe" || !u || !res) {
    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">What do you need?</h1>
          <p className="text-muted">Say it or type it in your own words. NEXA works out the rest.</p>
        </div>
        <Card className="!p-5">
          <div className="flex items-start gap-3">
            <Textarea
              aria-label="Describe what you need"
              rows={4}
              maxLength={1000}
              value={interim ? `${text}${text ? " " : ""}${interim}` : text}
              onChange={(e) => setText(e.target.value)}
              placeholder="e.g. Nexa, I need someone to help me move a cupboard."
              className="text-base"
            />
            <MicButton onInterim={setInterim} onTranscript={(t) => setText((x) => (x ? `${x} ${t}` : t))} />
          </div>
          <p className="mt-1 text-right text-xs text-muted">{text.length}/1000</p>
        </Card>

        {!coords && (
          <Notice tone="warn">
            <p className="font-semibold">I need to know where you are to find nearby help.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={loc.request} loading={loc.status === "asking"}>Use my location</Button>
              <Button size="sm" variant="secondary" onClick={() => void loc.useSample()}>Use sample location</Button>
            </div>
            {loc.status === "denied" && <p className="mt-2 text-danger">Location is blocked in your browser settings.</p>}
          </Notice>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        <Button size="lg" className="w-full" onClick={() => void understand()} loading={checking} disabled={text.trim().length < 3}>
          Continue
        </Button>
        <p className="text-center text-xs text-muted">If someone is seriously hurt, call {"112"} first. NEXA connects neighbours and does not replace emergency services.</p>
      </div>
    );
  }

  /* ------------------ step 2 ------------------ */
  const circle = res.trusted_circle;
  return (
    <div className={cx("mx-auto max-w-2xl space-y-5", critical && "emergency -mx-4 rounded-3xl bg-bg p-4 text-ink sm:mx-auto")}>
      <div className="flex items-center gap-3">
        <button onClick={() => setStep("describe")} className="grid h-10 w-10 place-items-center rounded-full hover:bg-surface2" aria-label="Back">←</button>
        <h1 className="text-2xl font-bold tracking-tight">{critical ? "This sounds serious" : "Here's what I understood"}</h1>
      </div>

      {critical && (
        <div role="alert" className="rounded-2xl border-2 border-danger bg-dangersoft p-4">
          <p className="text-lg font-bold">If this is an emergency, call {res.emergency_advice?.match(/\d+/)?.[0] ?? "112"} now.</p>
          <p className="mt-1 text-sm">{res.emergency_advice} NEXA will alert your Trusted Circle and first-aid-trained neighbours at the same time, and guide you step by step.</p>
          <a href={`tel:${res.emergency_advice?.match(/\d+/)?.[0] ?? "112"}`} className="mt-3 inline-flex min-h-12 items-center rounded-xl bg-dangersolid px-5 font-bold text-white">📞 Call emergency number</a>
        </div>
      )}

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-2xl" aria-hidden>{catLabel?.icon}</span>
          <p className="min-w-0 basis-full text-lg font-semibold sm:flex-1 sm:basis-0">{u.title}</p>
          <UrgencyBadge urgency={u.urgency} />
          <Badge tone="brand">{u.source === "llm" ? "AI understood" : "Understood"} · {Math.round(u.confidence * 100)}%</Badge>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Category">
            {(id) => (
              <Select id={id} value={u.category} onChange={(e) => setU({ ...u, category: e.target.value, skills_required: ref.data?.categories.find((c) => c.slug === e.target.value)?.default_skills ?? [] })}>
                {ref.data?.categories.map((c) => <option key={c.slug} value={c.slug}>{c.icon} {c.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Urgency" hint={critical ? "Serious situations can't be lowered." : undefined}>
            {() => (
              <Segmented<Urgency> label="Urgency" value={u.urgency} onChange={(v) => !critical && setU({ ...u, urgency: v })} options={[{ value: "normal", label: "Normal" }, { value: "urgent", label: "Urgent" }, ...(critical ? [{ value: "critical" as Urgency, label: "Critical" }] : [])]} />
            )}
          </Field>
          {!critical && (
            <>
              <Field label="People needed">
                {(id) => <Input id={id} type="number" min={1} max={20} value={u.num_helpers} onChange={(e) => setU({ ...u, num_helpers: Math.max(1, Math.min(20, Number(e.target.value) || 1)) })} />}
              </Field>
              <Field label="When (optional)">{(id) => <Input id={id} maxLength={64} value={u.time_requirement ?? ""} onChange={(e) => setU({ ...u, time_requirement: e.target.value || null })} placeholder="e.g. tomorrow 5pm" />}</Field>
            </>
          )}
        </div>
        {u.skills_required.length > 0 && (
          <p className="text-sm text-muted">
            Skills needed: {u.skills_required.map((s) => <Badge key={s} className="mr-1">{s.replace(/_/g, " ")}</Badge>)}
          </p>
        )}
      </Card>

      {/* routing */}
      {!critical && (
        <fieldset className="space-y-3">
          <legend className="mb-2 text-lg font-semibold">How should NEXA find help?</legend>
          {urgentish && <Notice tone="warn">This is urgent, so NEXA asks your Trusted Circle and nearby suitable helpers at the same time, without waiting.</Notice>}

          <RouteCard id="circle_first" routing={routing} set={setRouting} title="Ask my Trusted Circle first" body="Try nearby family, relatives and trusted contacts." disabled={circle.count === 0}>
            {circle.count === 0 ? (
              <p className="text-sm text-muted">No reachable Trusted Circle members nearby yet. <a className="text-brandtext underline" href="/circle">Add people</a></p>
            ) : (
              <>
                <p className="mb-2 text-sm font-semibold">Your Trusted Circle</p>
                <ul className="space-y-1.5">
                  {circle.members.map((m) => (
                    <li key={m.id} className="flex items-center gap-2 text-sm">
                      <span className={m.available ? "text-ok" : "text-muted"} aria-label={m.available ? "available" : "not marked available"}>{m.available ? "🟢" : "⚪"}</span>
                      <span className="flex-1">{m.name}</span>
                      <span className="text-muted">{fmtDistance(m.distance_km)}</span>
                    </li>
                  ))}
                </ul>
                {!urgentish && <p className="mt-2 text-sm text-muted">Response window: <b>{fmtCountdown(windowS * 1000)}</b> min. If nobody accepts, NEXA moves on to community helpers automatically.</p>}
              </>
            )}
          </RouteCard>

          <RouteCard id="community" routing={routing} set={setRouting} title="Find community help" body="Match me directly with suitable nearby helpers." />

          <RouteCard id="custom" routing={routing} set={setRouting} title="Customize" body="Choose exactly who receives this request.">
            <div className="space-y-1.5">
              {circle.members.map((m) => (
                <CustomPick key={`c${m.id}`} id={m.id} checked={custom.has(m.id)} set={setCustom} label={`${m.name} (Trusted Circle)`} note={fmtDistance(m.distance_km)} />
              ))}
              {helpers.slice(0, 8).filter((h) => !circle.members.some((m) => m.id === h.id)).map((h) => (
                <CustomPick key={`h${h.id}`} id={h.id} checked={custom.has(h.id)} set={setCustom} label={`Verified nearby helper${h.verified ? " ✓" : ""}`} note={`${fmtDistance(h.distance_km)}${h.trust_score != null ? ` · trust ${Math.round(h.trust_score)}` : ""}`} />
              ))}
              {circle.members.length === 0 && helpers.length === 0 && <p className="text-sm text-muted">No one is available nearby right now.</p>}
            </div>
          </RouteCard>
        </fieldset>
      )}

      <Card className="space-y-4">
        <Toggle checked={share} onChange={setShare} label="Share my exact location with the helper who accepts" description={critical ? "Recommended so help can find you. Others only ever see an approximate area." : "Others only ever see an approximate area."} />
        {!critical && routing !== "community" && (
          <Toggle checked={reveal} onChange={setReveal} label="Let helpers see how they're related to me" description={'Off: a stranger sees "Verified nearby helper", never "Nishit\'s cousin".'} />
        )}
        <p className="text-xs text-muted">Location: {coords ? `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}` : "unknown"} {coords && coords.lat === SAMPLE_LOCATION.lat ? "(sample)" : ""}</p>
      </Card>

      {error && <Notice tone="danger">{error}</Notice>}
      <Button size="lg" variant={critical ? "danger" : "primary"} className="w-full" onClick={() => void submit()} loading={submitting} disabled={routing === "custom" && !critical && custom.size === 0}>
        {critical ? "🚨 Start NEXA CARE and alert help" : routing === "circle_first" ? "Ask Trusted Circle" : routing === "custom" ? `Send to ${custom.size} selected` : "Find community help"}
      </Button>
    </div>
  );
}

function RouteCard({ id, routing, set, title, body, children, disabled }: { id: Routing; routing: Routing; set: (r: Routing) => void; title: string; body: string; children?: React.ReactNode; disabled?: boolean }) {
  const on = routing === id;
  return (
    <div className={cx("rounded-2xl border-2 bg-surface p-4 transition", on ? "border-brand" : "border-line", disabled && "opacity-70")}>
      <label className="flex cursor-pointer items-start gap-3">
        <input type="radio" name="routing" className="mt-1 h-5 w-5 accent-[var(--brand)]" checked={on} onChange={() => set(id)} />
        <span>
          <span className="block font-semibold">{title}</span>
          <span className="block text-sm text-muted">{body}</span>
        </span>
      </label>
      {on && children && <div className="mt-3 border-t border-line pt-3">{children}</div>}
    </div>
  );
}

function CustomPick({ id, checked, set, label, note }: { id: number; checked: boolean; set: React.Dispatch<React.SetStateAction<Set<number>>>; label: string; note: string }) {
  return (
    <label className="flex min-h-10 cursor-pointer items-center gap-3 text-sm">
      <input type="checkbox" className="h-5 w-5 accent-[var(--brand)]" checked={checked} onChange={(e) => set((s) => { const n = new Set(s); if (e.target.checked) n.add(id); else n.delete(id); return n; })} />
      <span className="flex-1">{label}</span>
      <span className="text-muted">{note}</span>
    </label>
  );
}

export default function NewRequestPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <NewRequest />
    </Suspense>
  );
}
