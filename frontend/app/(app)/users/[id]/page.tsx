"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ReportModal } from "@/components/ReportModal";
import { TrustCard } from "@/components/TrustCard";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, SectionTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { Review } from "@/lib/types";

export default function UserPage() {
  const { id } = useParams<{ id: string }>();
  const uid = Number(id);
  const { user } = useAuth();
  const prof = useQuery(() => api<{ id: number; name: string; bio: string; skills: string[]; member_since: string }>(`/api/users/${uid}`), [uid]);
  const reviews = useQuery(() => api<Review[]>(`/api/users/${uid}/reviews?limit=10`), [uid]);
  const [report, setReport] = useState(false);

  if (prof.loading) return <LoadingBlock />;
  if (prof.error || !prof.data) return <ErrorState message={prof.error ?? "User not found"} onRetry={prof.reload} />;
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{prof.data.name}</h1>
        <p className="text-sm text-muted">On NEXA since {new Date(prof.data.member_since).toLocaleDateString()}</p>
        {prof.data.bio && <p className="mt-2">{prof.data.bio}</p>}
        <div className="mt-2 flex flex-wrap gap-1.5">{prof.data.skills.map((s) => <Badge key={s}>{s}</Badge>)}</div>
      </div>
      <TrustCard userId={uid} />
      <section>
        <SectionTitle>Reviews</SectionTitle>
        {reviews.loading ? <LoadingBlock /> : (reviews.data ?? []).length === 0 ? <EmptyState icon="⭐" title="No reviews yet" /> : (
          <ul className="space-y-2">{reviews.data!.map((r) => <li key={r.id}><Card className="!p-3"><p className="text-warn">{"★".repeat(r.rating)}<span className="text-line">{"★".repeat(5 - r.rating)}</span> <span className="text-sm text-muted">· {r.reviewer} · {timeAgo(r.created_at)}</span></p>{r.comment && <p className="text-sm">{r.comment}</p>}</Card></li>)}</ul>
        )}
      </section>
      {user && user.id !== uid && <Button variant="ghost" className="text-danger" onClick={() => setReport(true)}>Report this person</Button>}
      <ReportModal userId={report ? uid : null} onClose={() => setReport(false)} />
    </div>
  );
}
