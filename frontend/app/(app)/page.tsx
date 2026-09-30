"use client";
import { HeartHandshake, MapPin, Mic, Siren, Users } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { InviteCard, RequestRow } from "@/components/RequestCards";
import { Avatar, Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, Notice, SectionTitle, Toggle } from "@/components/ui";
import { useVoicePanel } from "@/components/voice-context";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CLOSED_STATUSES, greeting } from "@/lib/format";
import { SAMPLE_LOCATION, useLocation, useQuery, useToast } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import type { HelpRequest, Reference, TrustedCircle } from "@/lib/types";

function Home() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const voice = useVoicePanel();
  const toast = useToast();
  const loc = useLocation();
  const [ask, setAsk] = useState("");
  const [savingAvail, setSavingAvail] = useState(false);

  const mine = useQuery(() => api<HelpRequest[]>("/api/requests?scope=mine&limit=20"), []);
  const invited = useQuery(() => api<HelpRequest[]>("/api/requests?scope=invited"), []);
  const assigned = useQuery(() => api<HelpRequest[]>("/api/requests?scope=assigned&limit=20"), []);
  const circle = useQuery(() => api<TrustedCircle>("/api/trusted-circle"), [user?.lat, user?.lng]);
  const ref = useQuery(() => api<Reference>("/api/reference"), []);

  useLiveEvents((e) => {
    if (e.type === "request_update" || (e.type === "notification" && ["new_request", "urgent_request", "trusted_request", "request_cancelled", "request_filled"].includes(e.kind))) {
      void mine.reload();
      void invited.reload();
      void assigned.reload();
    }
    if (e.type === "notification" && e.kind.startsWith("relationship")) void circle.reload();
  });

  if (!user) return null;
  const activeMine = (mine.data ?? []).filter((r) => !CLOSED_STATUSES.includes(r.status));
  const activeAssigned = (assigned.data ?? []).filter((r) => !CLOSED_STATUSES.includes(r.status));
  const noLocation = user.lat == null;

  async function toggleAvailable(v: boolean) {
    if (v && noLocation) {
      toast.push({ kind: "info", title: "Share your location first", body: "Helpers are matched by distance." });
      return;
    }
    setSavingAvail(true);
    try {
      setUser(await api("/api/users/me", { method: "PATCH", body: { is_available: v } }));
      toast.push({ kind: "success", title: v ? "You're visible to neighbours who need help" : "You're no longer available" });
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't update availability", body: errorMessage(e) });
    } finally {
      setSavingAvail(false);
    }
  }

  return (
    <div className="space-y-6">
      {params.get("welcome") && (
        <Notice tone="ok">
          Welcome to NEXA, {user.name.split(" ")[0]}! Start by sharing your location, then add people to your Trusted Circle.
        </Notice>
      )}

      <section>
        <p className="text-sm text-muted">{greeting()},</p>
        <h1 className="text-3xl font-bold tracking-tight">{user.name.split(" ")[0]}</h1>
      </section>

      {noLocation && (
        <Card className="border-brand/40 bg-brandsoft">
          <p className="font-semibold"><span className="inline-flex items-center gap-2"><MapPin aria-hidden size={20} />Where are you?</span></p>
          <p className="mt-1 text-sm text-muted">NEXA needs your location to find people near you. It is only shared the way you choose in Privacy settings.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={loc.request} loading={loc.status === "asking"}>
              Use my location
            </Button>
            <Button variant="secondary" onClick={() => void loc.useSample()}>
              Use sample location ({SAMPLE_LOCATION.label})
            </Button>
          </div>
          {loc.status === "denied" && <p className="mt-2 text-sm text-danger">Location permission was denied. Allow it in your browser, or use the sample location.</p>}
          {loc.status === "unavailable" && <p className="mt-2 text-sm text-danger">This browser can&apos;t provide your location. Use the sample location instead.</p>}
          {loc.status === "error" && <p className="mt-2 text-sm text-danger">We couldn&apos;t get your position. Try again or use the sample location.</p>}
        </Card>
      )}

      {/* ASK */}
      <Card className="!p-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (ask.trim().length >= 3) router.push(`/request/new?text=${encodeURIComponent(ask.trim())}`);
          }}
        >
          <label htmlFor="ask" className="mb-2 block text-lg font-semibold">
            What do you need help with?
          </label>
          <div className="flex gap-2">
            <input id="ask" value={ask} onChange={(e) => setAsk(e.target.value)} maxLength={1000} placeholder="e.g. I need someone to help me move a cupboard" className="min-h-12 w-full rounded-xl border-2 border-linestrong bg-surface2 px-4 text-base text-ink placeholder:text-muted focus:border-brand" />
            <Button type="submit" size="lg" disabled={ask.trim().length < 3}>
              Ask
            </Button>
          </div>
        </form>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => voice.open()}>
            <Mic aria-hidden size={18} /> Talk to NEXA
          </Button>
          <Link href="/care" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-dangersoft px-4 font-semibold text-danger">
            <Siren aria-hidden size={18} /> I need urgent help
          </Link>
        </div>
      </Card>

      {/* INCOMING */}
      {(invited.data?.length ?? 0) > 0 && (
        <section aria-label="Requests for you">
          <SectionTitle>Someone needs your help</SectionTitle>
          <div className="space-y-3">
            {invited.data!.map((r) => (
              <InviteCard key={r.id} r={r} onChanged={() => { void invited.reload(); void assigned.reload(); }} />
            ))}
          </div>
        </section>
      )}
      {activeAssigned.length > 0 && (
        <section aria-label="Requests you are helping with">
          <SectionTitle>You&apos;re helping</SectionTitle>
          <div className="space-y-3">
            {activeAssigned.map((r) => (
              <RequestRow key={r.id} r={r} />
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          <section aria-label="Quick actions">
            <SectionTitle>Quick actions</SectionTitle>
            {ref.error ? (
              <ErrorState message={ref.error} onRetry={ref.reload} />
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {(ref.data?.categories ?? []).filter((c) => c.slug !== "other").map((c) => (
                  <Link key={c.slug} href={`/request/new?category=${c.slug}`} className="clay-card clay-card-hover flex min-h-14 items-center gap-3 !rounded-2xl px-3 py-2 text-sm font-semibold">
                    <span className="text-xl" aria-hidden>
                      {c.icon}
                    </span>
                    {c.label}
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section aria-label="My requests">
            <SectionTitle action={<Link href="/request/new" className="text-sm font-semibold text-brandtext">New request</Link>}>My requests</SectionTitle>
            {mine.loading ? (
              <LoadingBlock />
            ) : mine.error ? (
              <ErrorState message={mine.error} onRetry={mine.reload} />
            ) : activeMine.length === 0 ? (
              <EmptyState icon={<HeartHandshake size={26} />} title="No open requests" body="When you ask for help, you can follow it here in real time." action={<Link href="/request/new" className="font-semibold text-brandtext">Ask for help →</Link>} />
            ) : (
              <div className="space-y-3">
                {activeMine.map((r) => (
                  <RequestRow key={r.id} r={r} />
                ))}
              </div>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <Card tone="mint">
            <Toggle checked={user.is_available} onChange={toggleAvailable} disabled={savingAvail} label="I can help neighbours" description="Get notified when someone nearby needs your skills." />
          </Card>
          <Card>
            <SectionTitle action={<Link href="/circle" className="text-sm font-semibold text-brandtext">Manage</Link>}>Trusted Circle</SectionTitle>
            {circle.loading ? (
              <LoadingBlock />
            ) : circle.error ? (
              <ErrorState message={circle.error} onRetry={circle.reload} />
            ) : circle.data && circle.data.total > 0 ? (
              <>
                <p className="text-sm">
                  <b>{circle.data.nearby_count}</b> of {circle.data.total} trusted contacts are nearby and reachable.
                </p>
                <ul className="mt-3 space-y-2">
                  {[...circle.data.groups.family, ...circle.data.groups.friends, ...circle.data.groups.other].slice(0, 5).map((e) => (
                    <li key={e.id} className="flex items-center gap-2 text-sm">
                      <span className={e.nearby && e.available ? "text-ok" : "text-muted"} aria-label={e.nearby && e.available ? "available" : "not available"}>
                        ●
                      </span>
                      <Avatar name={e.user.name} size={24} />
                      <span className="flex-1 truncate">{e.user.name}</span>
                      <Badge>{e.label}</Badge>
                    </li>
                  ))}
                </ul>
                {circle.data.pending.some((p) => p.can_respond) && <Notice tone="brand" className="mt-3">You have a Trusted Circle invitation waiting.</Notice>}
              </>
            ) : (
              <EmptyState icon={<Users size={26} />} title="Add people you trust" body="Family and friends can be asked first when you need help." action={<Link href="/circle" className="font-semibold text-brandtext">Build your circle →</Link>} />
            )}
          </Card>
          <Card tone="yellow">
            <p className="text-sm font-semibold text-ink">Help Credits</p>
            <p className="text-3xl font-bold">{user.credits}</p>
            <p className="text-xs text-muted">Earn credits by helping. Spend them when you receive help.</p>
          </Card>
        </aside>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <Home />
    </Suspense>
  );
}
