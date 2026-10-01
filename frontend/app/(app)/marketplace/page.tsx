"use client";
import { Gift, MapPin, Phone, Plus, Store, Wrench } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, Notice, Segmented, Select, Textarea, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtDistance } from "@/lib/format";
import { SAMPLE_LOCATION, useLocation, useQuery, useToast } from "@/lib/hooks";
import type { Listing, ListingKind } from "@/lib/types";

type Tab = "" | ListingKind | "mine";

const TABS: { value: Tab; label: string }[] = [
  { value: "", label: "All" },
  { value: "sell", label: "For sale" },
  { value: "gift", label: "Free gifts" },
  { value: "service", label: "Services" },
  { value: "mine", label: "My listings" },
];

const CATEGORIES: Record<ListingKind, string[]> = {
  sell: ["furniture", "electronics", "appliances", "books", "clothing", "kids", "sports", "other"],
  gift: ["furniture", "electronics", "appliances", "books", "clothing", "kids", "food", "plants", "other"],
  service: ["pest_control", "plumbing", "electrical", "cleaning", "carpentry", "ac_repair", "painting", "tutoring", "other"],
};
const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const price = (l: Listing) => (l.kind === "gift" ? "Free" : l.price != null ? `₹${l.price.toLocaleString("en-IN")}${l.kind === "service" ? " onwards" : ""}` : "Quote on request");

const KIND_META = {
  sell: { icon: Store, tone: "info" as const, text: "For sale" },
  gift: { icon: Gift, tone: "ok" as const, text: "Free gift" },
  service: { icon: Wrench, tone: "brand" as const, text: "Service" },
};

export default function MarketplacePage() {
  const loc = useLocation();
  const [tab, setTab] = useState<Tab>("");
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [posting, setPosting] = useState(false);
  const [asking, setAsking] = useState<Listing | null>(null);
  const [managing, setManaging] = useState<number | null>(null);

  const browse = tab !== "mine";
  const feed = useQuery(
    browse && loc.coords
      ? () => api<Listing[]>(`/api/marketplace?${new URLSearchParams({ ...(tab ? { kind: tab } : {}), ...(cat ? { category: cat } : {}), ...(q ? { q } : {}) })}`)
      : null,
    [tab, cat, q, loc.coords?.lat, loc.coords?.lng],
  );
  const mine = useQuery(!browse ? () => api<{ posted: Listing[]; requested: Listing[] }>("/api/marketplace/mine") : null, [tab]);
  const reload = () => void (browse ? feed.reload() : mine.reload());
  const cats = tab && tab !== "mine" ? CATEGORIES[tab] : [...new Set(Object.values(CATEGORIES).flat())];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Marketplace</h1>
          <p className="text-muted">Buy, sell, gift and book trusted services within your neighbourhood.</p>
        </div>
        <Button onClick={() => setPosting(true)}><Plus aria-hidden size={18} /> Post a listing</Button>
      </div>

      <div className="max-w-full overflow-x-auto"><Segmented label="Listing type" value={tab} onChange={(v) => { setTab(v); setCat(""); }} options={TABS} /></div>

      {browse && (
        <div className="flex flex-wrap gap-3">
          <Input aria-label="Search the marketplace" placeholder="Search listings…" value={q} onChange={(e) => setQ(e.target.value)} maxLength={80} className="max-w-xs" />
          <Select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} className="max-w-[14rem]">
            <option value="">All categories</option>
            {cats.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </Select>
        </div>
      )}

      {browse && !loc.coords ? (
        <EmptyState icon={<MapPin size={26} />} title="Share your location to see what's nearby"
          action={<div className="flex flex-wrap justify-center gap-2"><Button size="sm" onClick={loc.request}>Use my location</Button><Button size="sm" variant="secondary" onClick={() => void loc.useSample()}>Use sample location ({SAMPLE_LOCATION.label})</Button></div>} />
      ) : browse ? (
        feed.loading ? <LoadingBlock /> : feed.error ? <ErrorState message={feed.error} onRetry={feed.reload} /> : (feed.data ?? []).length === 0 ? (
          <EmptyState icon={<Store size={26} />} title="Nothing here yet" body="Be the first to post something for your neighbours." />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">{feed.data!.map((l) => <li key={l.id}><ListingCard l={l} onAsk={() => setAsking(l)} onManage={() => setManaging(l.id)} /></li>)}</ul>
        )
      ) : mine.loading ? <LoadingBlock /> : mine.error ? <ErrorState message={mine.error} onRetry={mine.reload} /> : (
        <div className="space-y-6">
          <section aria-labelledby="posted-h">
            <h2 id="posted-h" className="mb-2 text-lg font-bold">Posted by me</h2>
            {(mine.data?.posted ?? []).length === 0 ? <p className="text-muted">You haven&apos;t posted anything yet.</p> : (
              <ul className="grid gap-3 sm:grid-cols-2">{mine.data!.posted.map((l) => <li key={l.id}><ListingCard l={l} onAsk={() => undefined} onManage={() => setManaging(l.id)} /></li>)}</ul>
            )}
          </section>
          <section aria-labelledby="req-h">
            <h2 id="req-h" className="mb-2 text-lg font-bold">Asked for by me</h2>
            {(mine.data?.requested ?? []).length === 0 ? <p className="text-muted">Gifts and items you ask for will show up here.</p> : (
              <ul className="grid gap-3 sm:grid-cols-2">{mine.data!.requested.map((l) => <li key={l.id}><ListingCard l={l} onAsk={() => setAsking(l)} onManage={() => undefined} onChanged={reload} /></li>)}</ul>
            )}
          </section>
        </div>
      )}

      <PostModal open={posting} onClose={() => setPosting(false)} onPosted={() => { setPosting(false); setTab("mine"); void mine.reload(); }} />
      <AskModal listing={asking} onClose={() => setAsking(null)} onDone={() => { setAsking(null); reload(); }} />
      <ManageModal id={managing} onClose={() => setManaging(null)} onChanged={reload} />
    </div>
  );
}

function ListingCard({ l, onAsk, onManage, onChanged }: { l: Listing; onAsk: () => void; onManage: () => void; onChanged?: () => void }) {
  const toast = useToast();
  const meta = KIND_META[l.kind];
  const Icon = meta.icon;
  async function withdraw() {
    try {
      await api(`/api/marketplace/${l.id}/claims/${l.my_claim!.id}/withdraw`, { method: "POST" });
      onChanged?.();
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't withdraw", body: errorMessage(e) });
    }
  }
  const claim = l.my_claim && l.my_claim.status !== "withdrawn" ? l.my_claim : null;
  const verb = l.kind === "service" ? "Enquire" : l.kind === "gift" ? "Ask for this" : "I'm interested";
  return (
    <Card as="article" className={cx(l.status === "closed" && "opacity-70")}>
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold">{l.title}</p>
        <span className="shrink-0 font-bold text-brandtext">{price(l)}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone={meta.tone}><Icon aria-hidden size={13} /> {meta.text}</Badge>
        <Badge>{label(l.category)}</Badge>
        {l.status !== "available" && <Badge tone="warn">{l.reserved_for_me ? "Reserved for you" : l.status === "reserved" ? "Reserved" : "Closed"}</Badge>}
      </div>
      {l.description && <p className="mt-2 line-clamp-3 text-sm text-muted">{l.description}</p>}
      <p className="mt-2 text-sm text-muted">
        {[l.is_mine ? "You" : l.owner.name + (l.owner.verified ? " (verified)" : ""), l.condition ? label(l.condition) : null, l.distance_km != null ? fmtDistance(l.distance_km) + " away" : null].filter(Boolean).join(" · ")}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {l.kind === "service" && l.contact_phone && (
          <a href={`tel:${l.contact_phone.replace(/\s/g, "")}`} className="inline-flex min-h-11 items-center gap-2 font-semibold text-brandtext"><Phone aria-hidden size={18} /> {l.contact_phone}</a>
        )}
        {l.is_mine ? (
          <Button size="sm" variant="secondary" onClick={onManage}>Manage{l.claim_count ? ` (${l.claim_count} new)` : ""}</Button>
        ) : claim ? (
          <>
            <Badge tone={claim.status === "accepted" ? "ok" : claim.status === "declined" ? "danger" : "neutral"}>Your request: {claim.status}</Badge>
            {claim.status !== "declined" && <Button size="sm" variant="ghost" onClick={() => void withdraw()}>Withdraw</Button>}
          </>
        ) : l.status === "available" ? (
          <Button size="sm" variant={l.kind === "gift" ? "success" : "primary"} onClick={onAsk}>{verb}</Button>
        ) : null}
      </div>
    </Card>
  );
}

function AskModal({ listing, onClose, onDone }: { listing: Listing | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function send() {
    if (!listing) return;
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/marketplace/${listing.id}/claims`, { method: "POST", body: { message: msg.trim() } });
      toast.push({ kind: "success", title: "Sent", body: "The owner has been notified and will reply here." });
      setMsg("");
      onDone();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={!!listing} onClose={onClose} title={listing ? `${listing.kind === "service" ? "Enquire about" : "Ask for"}: ${listing.title}` : ""}>
      <div className="space-y-3">
        <Field label="Message to the owner" hint="Say when you can pick up, or what you need done.">
          {(id, a) => <Textarea id={id} {...a} rows={3} maxLength={500} value={msg} onChange={(e) => setMsg(e.target.value)} />}
        </Field>
        {err && <Notice tone="danger">{err}</Notice>}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={() => void send()}>Send</Button></div>
      </div>
    </Modal>
  );
}

function PostModal({ open, onClose, onPosted }: { open: boolean; onClose: () => void; onPosted: () => void }) {
  const toast = useToast();
  const [kind, setKind] = useState<ListingKind>("gift");
  const [category, setCategory] = useState("furniture");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [condition, setCondition] = useState("good");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function pickKind(k: ListingKind) {
    setKind(k);
    setCategory(CATEGORIES[k][0]);
    setErr(null);
  }
  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api("/api/marketplace", {
        method: "POST",
        body: {
          kind, category, title: title.trim(), description: description.trim(),
          price: kind !== "gift" && amount ? Number(amount) : null,
          condition: kind === "service" ? null : condition,
          contact_phone: kind === "service" ? phone.trim() : null,
        },
      });
      toast.push({ kind: "success", title: "Listing posted", body: "Neighbours nearby can see it now." });
      setTitle(""); setDescription(""); setAmount(""); setPhone("");
      onPosted();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Post a listing">
      <div className="space-y-3">
        <Segmented label="What are you posting?" value={kind} onChange={pickKind} options={[{ value: "gift", label: "Free gift" }, { value: "sell", label: "Sell an item" }, { value: "service", label: "Offer a service" }]} />
        <Field label="Title" required>{(id, a) => <Input id={id} {...a} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} placeholder={kind === "service" ? "e.g. Pest control for flats" : "e.g. Wooden study table"} />}</Field>
        <Field label="Category" required>{(id) => <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES[kind].map((c) => <option key={c} value={c}>{label(c)}</option>)}</Select>}</Field>
        <Field label="Details">{(id, a) => <Textarea id={id} {...a} rows={3} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        {kind !== "gift" && <Field label={kind === "service" ? "Starting price (₹)" : "Price (₹)"} required={kind === "sell"}>{(id, a) => <Input id={id} {...a} type="number" min={0} inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />}</Field>}
        {kind !== "service" && <Field label="Condition">{(id) => <Select id={id} value={condition} onChange={(e) => setCondition(e.target.value)}>{["new", "like_new", "good", "fair"].map((c) => <option key={c} value={c}>{label(c)}</option>)}</Select>}</Field>}
        {kind === "service" && <Field label="Contact number" required hint="Shown publicly so neighbours can book you.">{(id, a) => <Input id={id} {...a} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />}</Field>}
        <p className="text-xs text-muted">Only your approximate area (about 100 m) is shared, never your address.</p>
        {err && <Notice tone="danger">{err}</Notice>}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={() => void submit()}>Post</Button></div>
      </div>
    </Modal>
  );
}

function ManageModal({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, error, reload } = useQuery(id ? () => api<Listing>(`/api/marketplace/${id}`) : null, [id]);
  async function act(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown, closeAfter = false) {
    try {
      await api(`/api/marketplace/${id}${path}`, { method, body });
      onChanged();
      if (closeAfter) onClose();
      else await reload();
    } catch (e) {
      toast.push({ kind: "error", title: "Couldn't update", body: errorMessage(e) });
    }
  }
  return (
    <Modal open={id !== null} onClose={onClose} title={data?.title ?? "Manage listing"} wide>
      {error ? <ErrorState message={error} onRetry={reload} /> : !data ? <LoadingBlock /> : (
        <div className="space-y-4">
          <h3 className="font-bold">Requests ({data.claims?.length ?? 0})</h3>
          {(data.claims ?? []).length === 0 ? <p className="text-muted">No one has asked yet.</p> : (
            <ul className="space-y-2">
              {data.claims!.map((c) => (
                <li key={c.id} className="rounded-2xl border-2 border-line p-3">
                  <p className="font-semibold">{c.user.name}{c.user.verified ? " (verified)" : ""} <Badge className="ml-1">{c.status}</Badge></p>
                  {c.message && <p className="text-sm text-muted">{c.message}</p>}
                  {c.status === "pending" && data.status === "available" && (
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" variant="success" onClick={() => void act(`/claims/${c.id}/accept`, "POST")}>{data.kind === "service" ? "Accept" : "Give to them"}</Button>
                      <Button size="sm" variant="secondary" onClick={() => void act(`/claims/${c.id}/decline`, "POST")}>Decline</Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap justify-between gap-2 border-t-2 border-line pt-3">
            <Button variant="danger" size="sm" onClick={() => void act("", "DELETE", undefined, true)}>Delete listing</Button>
            {data.status !== "closed"
              ? <Button size="sm" variant="secondary" onClick={() => void act("", "PATCH", { status: "closed" })}>{data.kind === "gift" ? "Mark as given away" : data.kind === "sell" ? "Mark as sold" : "Stop listing"}</Button>
              : <Button size="sm" variant="secondary" onClick={() => void act("", "PATCH", { status: "available" })}>Re-open</Button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
