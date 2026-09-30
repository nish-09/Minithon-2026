"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { fmtDuration } from "@/lib/format";
import type { TrustCardData } from "@/lib/types";
import { Avatar, Badge, Card, ErrorState, LoadingBlock, Modal, ProgressBar, cx } from "./ui";

export function scoreTone(score: number): "ok" | "warn" | "danger" {
  return score >= 75 ? "ok" : score >= 50 ? "warn" : "danger";
}

export function ScoreRing({ score, size = 76 }: { score: number; size?: number }) {
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  const tone = scoreTone(score);
  const color = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--danger)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Trust score ${Math.round(score)} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="7" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="7" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} style={{ transition: "stroke-dashoffset .6s ease" }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center leading-none">
        <div>
          <div className="text-xl font-bold">{Math.round(score)}</div>
          <div className="text-[10px] text-muted">/100</div>
        </div>
      </div>
    </div>
  );
}

export function TrustCardView({ data, compact }: { data: TrustCardData; compact?: boolean }) {
  const [why, setWhy] = useState(!compact);
  const s = data.stats;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Avatar name={data.name} src={data.avatar_url} size={56} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-semibold">{data.name}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {data.badges.includes("identity_verified") && <Badge tone="ok">✓ Identity verified</Badge>}
            {data.certifications.map((c) => (
              <Badge key={c} tone="brand">
                ✓ {c}
              </Badge>
            ))}
            {data.confidence < 0.3 && <Badge tone="warn">Limited history</Badge>}
          </div>
        </div>
        <ScoreRing score={data.score} />
      </div>

      <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        <li>✓ {s.completed} helps completed</li>
        <li>{s.response_rate != null ? `✓ ${s.response_rate}% response rate` : "• No response data yet"}</li>
        <li>{s.rating != null ? `⭐ ${s.rating.toFixed(1)} community rating (${s.review_count})` : "• No reviews yet"}</li>
        <li>{s.avg_response_seconds != null ? `⏱ Replies in ~${fmtDuration(s.avg_response_seconds)}` : "• Reply time unknown"}</li>
      </ul>

      <div className="space-y-2.5">
        {data.components.map((c) => (
          <div key={c.key}>
            <div className="mb-1 flex justify-between text-sm">
              <span>{c.label}</span>
              <span className="font-semibold tabular-nums">{Math.round(c.score)}</span>
            </div>
            <ProgressBar value={c.score} tone={scoreTone(c.score)} label={c.label} />
          </div>
        ))}
      </div>

      {data.categories.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Trust by category</p>
          <div className="flex flex-wrap gap-2">
            {data.categories.map((c) => (
              <span key={c.category} className="rounded-lg bg-surface2 px-2.5 py-1 text-sm">
                {c.label} <b className="tabular-nums">{Math.round(c.score)}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <button type="button" onClick={() => setWhy((w) => !w)} aria-expanded={why} className="text-sm font-semibold text-brandtext">
          {why ? "Hide" : "Why this score?"} {why ? "▴" : "▾"}
        </button>
        {why && (
          <ul className="mt-2 space-y-2">
            {data.factors.map((f) => (
              <li key={f.key} className="flex gap-2 text-sm">
                <span aria-hidden className={cx("mt-0.5", f.impact === "positive" ? "text-ok" : f.impact === "negative" ? "text-danger" : "text-muted")}>
                  {f.impact === "positive" ? "▲" : f.impact === "negative" ? "▼" : "●"}
                </span>
                <span>
                  <b>{f.label}.</b> <span className="text-muted">{f.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="text-xs text-muted">
        {data.disclaimer} Model: {data.model_version}.
      </p>
    </div>
  );
}

export function TrustCard({ userId, compact }: { userId: number; compact?: boolean }) {
  const { data, error, loading, reload } = useQuery(() => api<TrustCardData>(`/api/users/${userId}/trust`), [userId]);
  if (loading) return <LoadingBlock label="Loading Trust Card…" />;
  if (error || !data) return <ErrorState message={error ?? "Not available"} onRetry={reload} />;
  return (
    <Card className="!p-5">
      <TrustCardView data={data} compact={compact} />
    </Card>
  );
}

export function TrustCardModal({ userId, onClose }: { userId: number | null; onClose: () => void }) {
  return (
    <Modal open={userId !== null} onClose={onClose} title="Trust Card" wide>
      {userId !== null && <TrustCard userId={userId} />}
    </Modal>
  );
}

export function TrustChip({ score, onClick }: { score: number | null; onClick?: () => void }) {
  if (score == null) return null;
  const tone = scoreTone(score);
  const cls = tone === "ok" ? "bg-oksoft text-ok" : tone === "warn" ? "bg-warnsoft text-warn" : "bg-dangersoft text-danger";
  return (
    <button type="button" onClick={onClick} className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold", cls)} aria-label={`Trust ${Math.round(score)} out of 100. Open Trust Card`}>
      🛡 {Math.round(score)}
    </button>
  );
}
