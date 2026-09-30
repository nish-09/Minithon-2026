"use client";
import Link from "next/link";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { CLOSED_STATUSES, fmtDistance, timeAgo } from "@/lib/format";
import { useToast } from "@/lib/hooks";
import type { HelpRequest } from "@/lib/types";
import { Badge, Button, Card, StatusBadge, UrgencyBadge, cx } from "./ui";

export function RequestRow({ r }: { r: HelpRequest }) {
  const closed = CLOSED_STATUSES.includes(r.status);
  return (
    <Link href={`/requests/${r.id}`} className="block rounded-2xl focus-visible:outline-offset-4">
      <Card as="article" className={cx("flex items-center gap-4 transition hover:border-brand/50", r.urgency === "critical" && !closed && "border-danger/50")}>
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-surface2 text-2xl" aria-hidden>
          {r.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{r.title}</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusBadge status={r.status} /> {timeAgo(r.created_at)}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <UrgencyBadge urgency={r.urgency} />
          {r.assignments?.[0]?.eta_minutes != null && !closed && <Badge tone="ok" icon="⏱">ETA {Math.round(r.assignments[0].eta_minutes)} min</Badge>}
        </div>
      </Card>
    </Link>
  );
}

/** A request someone else asked me to help with: accept or decline. */
export function InviteCard({ r, onChanged }: { r: HelpRequest; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);
  const circle = r.channel === "circle";

  async function act(kind: "accept" | "decline") {
    setBusy(kind);
    try {
      await api(`/api/matching/${r.id}/${kind === "accept" ? "accept" : "reject"}`, { method: "POST" });
      toast.push({ kind: "success", title: kind === "accept" ? "You're on it. Thank you!" : "Declined" });
    } catch (e) {
      toast.push({ kind: "error", title: kind === "accept" ? "Couldn't accept" : "Couldn't decline", body: errorMessage(e) });
    } finally {
      setBusy(null);
      onChanged();
    }
  }

  return (
    <Card as="article" className={cx(r.urgency === "critical" ? "border-danger/60 bg-dangersoft/40" : r.urgency === "urgent" ? "border-warn/50" : "")}>
      <div className="flex items-start gap-3">
        <span className="text-2xl" aria-hidden>
          {r.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold">{r.title}</p>
            <UrgencyBadge urgency={r.urgency} />
            {circle && <Badge tone="brand">Trusted Circle</Badge>}
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {r.requester?.name} · {fmtDistance(r.distance_km)} away · {timeAgo(r.created_at)}
            {r.relationship_label ? ` · ${r.relationship_label}` : ""}
          </p>
          {r.location_approximate && <p className="text-xs text-muted">Approximate location. Exact location is shared only with the person who accepts.</p>}
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        {r.can_accept ? (
          <>
            <Button variant="success" className="flex-1" loading={busy === "accept"} disabled={busy !== null} onClick={() => void act("accept")}>
              Accept
            </Button>
            {r.my_recipient_state === "NOTIFIED" && (
              <Button variant="secondary" className="flex-1" loading={busy === "decline"} disabled={busy !== null} onClick={() => void act("decline")}>
                Decline
              </Button>
            )}
          </>
        ) : (
          <Badge>No longer available</Badge>
        )}
        <Link href={`/requests/${r.id}`} className="grid min-h-11 place-items-center rounded-xl px-4 text-sm font-semibold text-brandtext hover:bg-brandsoft">
          Details
        </Link>
      </div>
    </Card>
  );
}
