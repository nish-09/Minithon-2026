"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RequestRow } from "@/components/RequestCards";
import { TrustCard } from "@/components/TrustCard";
import { Avatar, Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, SectionTitle, Select, Textarea, Toggle } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { SAMPLE_LOCATION, useLocation, useQuery, useToast } from "@/lib/hooks";
import type { HelpRequest, Me, Reference, Review, TrustedCircle } from "@/lib/types";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_LABEL: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

export default function ProfilePage() {
  const { user } = useAuth();
  return user ? <ProfileInner key={user.id} user={user} /> : null;
}

function ProfileInner({ user }: { user: Me }) {
  const { setUser, logout } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const loc = useLocation();
  const ref = useQuery(() => api<Reference>("/api/reference"), []);
  const reviews = useQuery(() => api<Review[]>(`/api/users/${user.id}/reviews?limit=10`), [user.id]);
  const history = useQuery(() => api<HelpRequest[]>("/api/requests?scope=assigned&limit=20"), []);
  const credits = useQuery(() => api<{ balance: number; transactions: { id: number; amount: number; kind: string; created_at: string }[] }>("/api/credits"), [user.credits]);
  const circle = useQuery(() => api<TrustedCircle>("/api/trusted-circle"), []);

  const [form, setForm] = useState({ name: user.name, phone: user.phone ?? "", bio: user.bio, avatar_url: user.avatar_url ?? "" });
  const [skills, setSkills] = useState<Record<string, number>>(() => Object.fromEntries(user.skills.map((s) => [s.slug, s.years_experience])));
  const [certs, setCerts] = useState<Set<string>>(() => new Set(user.certifications.map((c) => c.slug)));
  const [sched, setSched] = useState<Record<string, string[]>>(() => user.availability_schedule ?? {});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [donate, setDonate] = useState({ to: "", amount: 5 });

  async function save() {
    setErr(null);
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(), bio: form.bio,
        skills: Object.entries(skills).map(([slug, years_experience]) => ({ slug, years_experience })),
        certifications: [...certs], availability_schedule: sched,
      };
      if (form.phone !== (user.phone ?? "") && form.phone) body.phone = form.phone;
      if (form.avatar_url && form.avatar_url !== (user.avatar_url ?? "")) body.avatar_url = form.avatar_url;
      setUser(await api("/api/users/me", { method: "PATCH", body }));
      toast.push({ kind: "success", title: "Profile saved" });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  async function quick(body: Record<string, unknown>) {
    try { setUser(await api("/api/users/me", { method: "PATCH", body })); }
    catch (e) { toast.push({ kind: "error", title: "Couldn't update", body: errorMessage(e) }); }
  }

  const done = (history.data ?? []).filter((r) => ["COMPLETED", "RATED"].includes(r.status));
  const members = [...(circle.data?.groups.family ?? []), ...(circle.data?.groups.friends ?? []), ...(circle.data?.groups.other ?? [])];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Avatar name={user.name} src={user.avatar_url} size={72} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-bold tracking-tight">{user.name}</h1>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Badge tone={user.identity_verified ? "ok" : "warn"}>{user.identity_verified ? "✓ Identity verified" : "Identity not verified"}</Badge>
            <Badge tone={user.phone_verified ? "ok" : "neutral"}>{user.phone_verified ? "✓ Phone" : "Phone unverified"}</Badge>
            <Badge tone={user.email_verified ? "ok" : "neutral"}>{user.email_verified ? "✓ Email" : "Email unverified"}</Badge>
          </div>
        </div>
        <div className="text-right"><p className="text-3xl font-bold">{user.credits}</p><p className="text-xs text-muted">Help Credits</p></div>
      </div>
      {!user.identity_verified && <Notice tone="brand">Verification is reviewed by NEXA administrators. Verified identity and certifications raise your Trust Card.</Notice>}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <Card className="space-y-4">
            <SectionTitle>About you</SectionTitle>
            {err && <Notice tone="danger">{err}</Notice>}
            <Field label="Name">{(id) => <Input id={id} value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
            <Field label="Phone" hint="Changing your phone number removes its verification.">{(id) => <Input id={id} type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />}</Field>
            <Field label="Profile photo URL (optional)">{(id) => <Input id={id} type="url" placeholder="https://…" value={form.avatar_url} onChange={(e) => setForm({ ...form, avatar_url: e.target.value })} />}</Field>
            <Field label="Bio">{(id) => <Textarea id={id} rows={3} maxLength={1000} value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} />}</Field>
          </Card>

          <Card className="space-y-3">
            <SectionTitle>Skills &amp; certifications</SectionTitle>
            <p className="text-sm text-muted">Pick what you can help with. Certifications you claim stay &quot;pending&quot; until an administrator verifies them.</p>
            <div className="space-y-2">
              {ref.data?.skills.map((s) => (
                <div key={s.slug} className="flex items-center gap-3">
                  <label className="flex min-h-10 flex-1 cursor-pointer items-center gap-3 text-sm">
                    <input type="checkbox" className="h-5 w-5 accent-[var(--brand)]" checked={s.slug in skills} onChange={(e) => setSkills((x) => { const n = { ...x }; if (e.target.checked) n[s.slug] = 1; else delete n[s.slug]; return n; })} />
                    {s.label}
                  </label>
                  {s.slug in skills && <label className="flex items-center gap-1.5 text-xs text-muted">yrs <input type="number" min={0} max={70} value={skills[s.slug]} onChange={(e) => setSkills((x) => ({ ...x, [s.slug]: Math.max(0, Math.min(70, Number(e.target.value) || 0)) }))} className="h-9 w-16 rounded-lg border-2 border-linestrong bg-surface px-2 text-ink" aria-label={`Years of experience in ${s.label}`} /></label>}
                </div>
              ))}
            </div>
            <div className="border-t border-line pt-3">
              <p className="mb-2 text-sm font-medium">Certifications</p>
              {ref.data?.certifications.map((c) => {
                const mine = user.certifications.find((x) => x.slug === c.slug);
                return (
                  <label key={c.slug} className="flex min-h-10 cursor-pointer items-center gap-3 text-sm">
                    <input type="checkbox" className="h-5 w-5 accent-[var(--brand)]" checked={certs.has(c.slug)} onChange={(e) => setCerts((x) => { const n = new Set(x); if (e.target.checked) n.add(c.slug); else n.delete(c.slug); return n; })} />
                    <span className="flex-1">{c.label}</span>
                    {mine && <Badge tone={mine.verified ? "ok" : "warn"}>{mine.verified ? "Verified" : "Pending review"}</Badge>}
                  </label>
                );
              })}
            </div>
          </Card>

          <Card className="space-y-3">
            <SectionTitle>Availability</SectionTitle>
            <Toggle checked={user.is_available} onChange={(v) => void quick({ is_available: v })} label="Available to help right now" description="Turn off to stop receiving requests." />
            <details className="text-sm">
              <summary className="cursor-pointer font-medium">Weekly schedule (optional)</summary>
              <p className="mt-2 text-xs text-muted">Outside these hours you rank lower in SmartMatch. Leave empty for no restriction.</p>
              <div className="mt-2 space-y-2">
                {DAYS.map((d) => {
                  const [start, end] = (sched[d]?.[0] ?? "").split("-");
                  const set = (s: string, e: string) => setSched((x) => { const n = { ...x }; if (s && e) n[d] = [`${s}-${e}`]; else delete n[d]; return n; });
                  return (
                    <div key={d} className="flex items-center gap-2">
                      <span className="w-24">{DAY_LABEL[d]}</span>
                      <input type="time" aria-label={`${DAY_LABEL[d]} from`} value={start ?? ""} onChange={(e) => set(e.target.value, end ?? "")} className="h-10 rounded-lg border-2 border-linestrong bg-surface px-2" />
                      <span>to</span>
                      <input type="time" aria-label={`${DAY_LABEL[d]} until`} value={end ?? ""} onChange={(e) => set(start ?? "", e.target.value)} className="h-10 rounded-lg border-2 border-linestrong bg-surface px-2" />
                    </div>
                  );
                })}
              </div>
            </details>
          </Card>

          <Button size="lg" className="w-full" loading={saving} disabled={form.name.trim().length < 2} onClick={() => void save()}>Save profile</Button>
        </div>

        <div className="space-y-6">
          <Card className="space-y-3">
            <SectionTitle>Location &amp; privacy</SectionTitle>
            <Field label="Location sharing" hint="“Only on requests” keeps your position private until you ask for or offer help. “Off” hides you from maps and matching.">
              {(id) => (
                <Select id={id} value={user.privacy.location_sharing} onChange={(e) => void quick({ location_sharing: e.target.value })}>
                  <option value="requests">Only when I ask for or offer help</option>
                  <option value="always">Always (so helpers can find me)</option>
                  <option value="off">Off</option>
                </Select>
              )}
            </Field>
            <p className="text-sm">{user.lat != null ? `Current position saved (${user.lat.toFixed(3)}, ${user.lng?.toFixed(3)})` : "No location saved."}</p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={loc.request} loading={loc.status === "asking"}>Update my location</Button>
              <Button size="sm" variant="ghost" onClick={() => void loc.useSample()}>Use sample ({SAMPLE_LOCATION.label})</Button>
              {user.lat != null && <Button size="sm" variant="ghost" className="text-danger" onClick={async () => { await api("/api/users/me/location", { method: "DELETE" }); location.reload(); }}>Delete my location</Button>}
            </div>
            {loc.status === "denied" && <p className="text-sm text-danger">Permission denied. Allow location in your browser settings.</p>}
          </Card>

          <section><SectionTitle>Your Trust Card</SectionTitle><TrustCard userId={user.id} /></section>

          <Card>
            <SectionTitle>Help Credits</SectionTitle>
            <p className="text-sm text-muted">Helping earns credits; receiving help uses them. They are a thank-you, not money. Gift some to someone in your circle:</p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Field label="To">{(id) => <Select id={id} value={donate.to} onChange={(e) => setDonate({ ...donate, to: e.target.value })}><option value="">Choose…</option>{members.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.name}</option>)}</Select>}</Field>
              <Field label="Credits">{(id) => <Input id={id} type="number" min={1} value={donate.amount} onChange={(e) => setDonate({ ...donate, amount: Math.max(1, Number(e.target.value) || 1) })} className="w-24" />}</Field>
              <Button disabled={!donate.to} onClick={async () => { try { await api("/api/credits/donate", { method: "POST", body: { to_user_id: Number(donate.to), amount: donate.amount } }); toast.push({ kind: "success", title: "Credits sent" }); void credits.reload(); const me = await api<Me>("/api/auth/me"); setUser(me); } catch (e) { toast.push({ kind: "error", title: "Couldn't send", body: errorMessage(e) }); } }}>Donate</Button>
            </div>
            {credits.data && (
              <ul className="mt-4 space-y-1 text-sm">
                {credits.data.transactions.slice(0, 6).map((t) => <li key={t.id} className="flex justify-between"><span className="capitalize">{t.kind}</span><span className={t.amount >= 0 ? "text-ok" : "text-danger"}>{t.amount > 0 ? "+" : ""}{t.amount} <span className="text-muted">· {timeAgo(t.created_at)}</span></span></li>)}
              </ul>
            )}
          </Card>

          <section>
            <SectionTitle>Reviews about you</SectionTitle>
            {reviews.loading ? <LoadingBlock /> : reviews.error ? <ErrorState message={reviews.error} onRetry={reviews.reload} /> : (reviews.data ?? []).length === 0 ? <EmptyState icon="⭐" title="No reviews yet" body="Reviews appear after you help someone." /> : (
              <ul className="space-y-2">{reviews.data!.map((r) => <li key={r.id}><Card className="!p-3"><p className="text-warn">{"★".repeat(r.rating)}<span className="text-line">{"★".repeat(5 - r.rating)}</span> <span className="text-sm text-muted">· {r.reviewer} · {timeAgo(r.created_at)}</span></p>{r.comment && <p className="text-sm">{r.comment}</p>}</Card></li>)}</ul>
            )}
          </section>

          <section>
            <SectionTitle>Help history</SectionTitle>
            {done.length === 0 ? <p className="text-sm text-muted">Requests you&apos;ve helped with will show here.</p> : <div className="space-y-2">{done.map((r) => <RequestRow key={r.id} r={r} />)}</div>}
          </section>

          <Button variant="secondary" className="w-full" onClick={() => void logout().then(() => router.replace("/login"))}>Log out</Button>
        </div>
      </div>
    </div>
  );
}
