"use client";
import { Users } from "lucide-react";
import { useState } from "react";
import { Avatar, Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, Notice, SectionTitle, Select, Toggle } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDistance } from "@/lib/format";
import { useQuery, useToast } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import type { Reference, RelationshipEdge, TrustedCircle } from "@/lib/types";

const GROUPS: { key: "family" | "friends" | "other"; title: string }[] = [
  { key: "family", title: "Family & Relatives" },
  { key: "friends", title: "Friends" },
  { key: "other", title: "Neighbors & others" },
];

export default function CirclePage() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const circle = useQuery(() => api<TrustedCircle>("/api/trusted-circle"), [user?.lat, user?.lng]);
  const ref = useQuery(() => api<Reference>("/api/reference"), []);
  const [addOpen, setAddOpen] = useState(false);
  const [confirm, setConfirm] = useState<{ edge: RelationshipEdge; kind: "remove" | "block" } | null>(null);

  useLiveEvents((e) => {
    if (e.type === "notification" && String(e.kind).startsWith("relationship")) void circle.reload();
  });

  async function patch(edge: RelationshipEdge, body: Record<string, unknown>) {
    try {
      await api(`/api/relationships/${edge.id}`, { method: "PATCH", body });
      await circle.reload();
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't update", body: errorMessage(e) });
    }
  }
  async function respond(edge: RelationshipEdge, kind: "accept" | "decline") {
    try {
      await api(`/api/relationships/${edge.id}/${kind}`, { method: "POST" });
      toast.push({ kind: "success", title: kind === "accept" ? `${edge.user.name} is now in your Trusted Circle` : "Invitation declined" });
      await circle.reload();
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't respond", body: errorMessage(e) });
    }
  }
  async function doConfirm() {
    if (!confirm) return;
    try {
      await api(confirm.kind === "remove" ? `/api/relationships/${confirm.edge.id}` : `/api/relationships/${confirm.edge.id}/block`, { method: confirm.kind === "remove" ? "DELETE" : "POST" });
      toast.push({ kind: "success", title: confirm.kind === "remove" ? "Removed from your circle" : "Blocked" });
      setConfirm(null);
      await circle.reload();
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't complete that", body: errorMessage(e) });
    }
  }

  async function savePrivacy(body: Record<string, unknown>) {
    try {
      setUser(await api("/api/users/me", { method: "PATCH", body }));
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't save setting", body: errorMessage(e) });
    }
  }

  if (!user) return null;
  const p = user.privacy;
  const incoming = (circle.data?.pending ?? []).filter((x) => x.can_respond);
  const outgoing = (circle.data?.pending ?? []).filter((x) => !x.can_respond);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trusted Circle</h1>
          <p className="text-muted">The people NEXA asks first when you need help.</p>
        </div>
        <Button onClick={() => setAddOpen(true)}>+ Add someone</Button>
      </div>

      {circle.loading ? (
        <LoadingBlock />
      ) : circle.error || !circle.data ? (
        <ErrorState message={circle.error ?? "Couldn't load"} onRetry={circle.reload} />
      ) : (
        <>
          {incoming.length > 0 && (
            <Card className="border-brand/40">
              <SectionTitle>Invitations</SectionTitle>
              <ul className="space-y-3">
                {incoming.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center gap-3">
                    <Avatar name={e.user.name} size={40} />
                    <p className="min-w-0 flex-1"><b>{e.user.name}</b> added you as their <b>{e.label.toLowerCase()}</b>. Accepting lets them contact you when they need help.</p>
                    <Button size="sm" variant="success" onClick={() => void respond(e, "accept")}>Accept</Button>
                    <Button size="sm" variant="secondary" onClick={() => void respond(e, "decline")}>Decline</Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {outgoing.length > 0 && (
            <Card>
              <SectionTitle>Waiting for a reply</SectionTitle>
              <ul className="space-y-2 text-sm">
                {outgoing.map((e) => (
                  <li key={e.id} className="flex items-center gap-3">
                    <Avatar name={e.user.name} size={28} /> <span className="flex-1">{e.user.name} · {e.label}</span>
                    <Badge tone="warn">Pending</Badge>
                    <button className="text-muted underline" onClick={() => setConfirm({ edge: e, kind: "remove" })}>Withdraw</button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {circle.data.total === 0 ? (
            <EmptyState icon={<Users size={26} />} title="Your circle is empty" body="Add family, relatives and friends who are on NEXA. Both of you must agree before the relationship is verified." action={<Button onClick={() => setAddOpen(true)}>Add your first person</Button>} />
          ) : (
            <>
              <Notice tone="brand">
                <b>{circle.data.nearby_count}</b> of {circle.data.total} people can be contacted and are nearby. Untick anyone you don&apos;t want NEXA to ask.
              </Notice>
              {GROUPS.map((g) => {
                const list = circle.data!.groups[g.key];
                if (list.length === 0) return null;
                return (
                  <section key={g.key} aria-label={g.title}>
                    <SectionTitle>{g.title}</SectionTitle>
                    <div className="space-y-3">
                      {list.map((e) => (
                        <Card key={e.id} as="article">
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <Avatar name={e.user.name} size={44} />
                            <div className="min-w-0 flex-1">
                              <p className="truncate font-semibold">
                                {e.user.name}
                              </p>
                              <p className="text-sm text-muted">
                                {e.label}
                                {e.distance_km != null ? ` · ${fmtDistance(e.distance_km)}` : " · location unknown"}
                                {e.eta_minutes != null ? ` · ~${Math.round(e.eta_minutes)} min` : ""}
                              </p>
                            </div>
                            <label className="flex min-h-11 w-full cursor-pointer items-center gap-2 text-sm font-medium sm:w-auto">
                              <input type="checkbox" className="h-5 w-5 accent-[var(--brand)]" checked={e.can_receive_requests} onChange={(ev) => void patch(e, { can_receive_requests: ev.target.checked })} />
                              Can be contacted
                            </label>
                          </div>
                          <div className="mt-3 grid gap-3 sm:grid-cols-3">
                            <Field label="Relationship">
                              {(id) => (
                                <Select id={id} value={e.relationship_type} onChange={(ev) => void patch(e, { relationship_type: ev.target.value })}>
                                  {ref.data?.relationship_types.map((r) => <option key={r.slug} value={r.slug}>{r.label}</option>)}
                                </Select>
                              )}
                            </Field>
                            <Field label="Priority" hint="1 = asked first">
                              {(id) => (
                                <Select id={id} value={e.priority} onChange={(ev) => void patch(e, { priority: Number(ev.target.value) })}>
                                  {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
                                </Select>
                              )}
                            </Field>
                            <Field label="Who can see this link?">
                              {(id) => (
                                <Select id={id} value={e.visibility} onChange={(ev) => void patch(e, { visibility: ev.target.value })}>
                                  <option value="circle">Trusted Circle members</option>
                                  <option value="me">Only me</option>
                                  <option value="nobody">Nobody, never reveal</option>
                                </Select>
                              )}
                            </Field>
                          </div>
                          <div className="mt-3 flex justify-end gap-3 text-sm">
                            <button className="text-muted underline" onClick={() => setConfirm({ edge: e, kind: "remove" })}>Remove</button>
                            <button className="text-danger underline" onClick={() => setConfirm({ edge: e, kind: "block" })}>Block</button>
                          </div>
                        </Card>
                      ))}
                    </div>
                  </section>
                );
              })}
            </>
          )}
        </>
      )}

      <Card className="space-y-4">
        <SectionTitle>Privacy &amp; preferences</SectionTitle>
        <Field label="Who can see my relationships?">
          {(id) => (
            <Select id={id} value={p.relationship_visibility} onChange={(e) => void savePrivacy({ relationship_visibility: e.target.value })}>
              <option value="me">Only me</option>
              <option value="circle">Trusted Circle members</option>
              <option value="nobody">Nobody publicly</option>
            </Select>
          )}
        </Field>
        <p className="-mt-2 text-xs text-muted">Strangers only ever see &quot;Verified nearby helper&quot;, never &quot;{user.name.split(" ")[0]}&apos;s cousin&quot;.</p>
        <Toggle checked={p.prefer_trusted_circle} onChange={(v) => void savePrivacy({ prefer_trusted_circle: v })} label="Prefer my Trusted Circle when matching" description="Family gets a boost in SmartMatch, but never overrides a clearly better nearby helper in an emergency." />
        <Toggle checked={p.prefer_circle_for_critical} onChange={(v) => void savePrivacy({ prefer_circle_for_critical: v })} label="Alert my circle in emergencies" description="They're told at the same time as nearby first-aiders. NEXA never waits for them in a critical incident." />
        <Toggle checked={p.reveal_relationship_to_helpers} onChange={(v) => void savePrivacy({ reveal_relationship_to_helpers: v })} label="Let helpers see how we're related by default" description="You can still change this on each request." />
        <Field label="Default: ask Trusted Circle first?">
          {(id) => (
            <Select id={id} value={p.trusted_circle_default_mode} onChange={(e) => void savePrivacy({ trusted_circle_default_mode: e.target.value })}>
              <option value="ask">Ask me each time (recommended)</option>
              <option value="circle">Trusted Circle first</option>
              <option value="community">Community directly</option>
            </Select>
          )}
        </Field>
        <Field label="How long to wait for my circle (normal requests)" hint="Urgent requests use a shorter window; critical incidents never wait.">
          {(id) => (
            <Select id={id} value={String(p.circle_window_override_s ?? 0)} onChange={(e) => void savePrivacy({ circle_window_override_s: Number(e.target.value) || null })}>
              <option value="0">Default (5 minutes)</option>
              <option value="120">2 minutes</option>
              <option value="600">10 minutes</option>
              <option value="900">15 minutes</option>
              <option value="1800">30 minutes</option>
            </Select>
          )}
        </Field>
      </Card>

      <AddModal open={addOpen} onClose={() => setAddOpen(false)} ref_={ref.data} onAdded={() => void circle.reload()} />
      <Modal open={confirm !== null} onClose={() => setConfirm(null)} title={confirm?.kind === "block" ? "Block this person?" : "Remove from your circle?"}>
        <p className="text-muted">
          {confirm?.kind === "block"
            ? `${confirm?.edge.user.name} will never be asked for your requests and can't invite you again.`
            : `${confirm?.edge.user.name} will stop being contacted for your requests. They will also lose this link.`}
        </p>
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" className="flex-1" onClick={() => void doConfirm()}>{confirm?.kind === "block" ? "Block" : "Remove"}</Button>
        </div>
      </Modal>
    </div>
  );
}

function AddModal({ open, onClose, ref_, onAdded }: { open: boolean; onClose: () => void; ref_: Reference | null; onAdded: () => void }) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [type, setType] = useState("friend");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError("Enter the email address they use on NEXA.");
    setBusy(true);
    try {
      await api("/api/relationships", { method: "POST", body: { email: email.trim(), relationship_type: type } });
      toast.push({ kind: "success", title: "Invitation sent", body: "Once they accept, the relationship is verified." });
      setEmail("");
      onAdded();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add to your Trusted Circle">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}
        <Field label="Their email on NEXA" hint="They'll get an invitation and must accept before anything is shared.">{(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />}</Field>
        <Field label="Who are they to you?">
          {(id) => (
            <Select id={id} value={type} onChange={(e) => setType(e.target.value)}>
              {(["family", "friends", "other"] as const).map((g) => (
                <optgroup key={g} label={g === "family" ? "Family & Relatives" : g === "friends" ? "Friends" : "Other"}>
                  {ref_?.relationship_types.filter((r) => r.group === g).map((r) => <option key={r.slug} value={r.slug}>{r.label}</option>)}
                </optgroup>
              ))}
            </Select>
          )}
        </Field>
        <Button type="submit" className="w-full" loading={busy}>Send invitation</Button>
      </form>
    </Modal>
  );
}
