"use client";
import { useState } from "react";
import { Badge, Card, EmptyState, ErrorState, Input, LoadingBlock, Segmented } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDistance } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { DirectoryItem } from "@/lib/types";

const CATS = [
  { value: "", label: "All" },
  { value: "emergency", label: "Emergency" },
  { value: "hospital", label: "Hospitals" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "plumber", label: "Plumbers" },
  { value: "electrician", label: "Electricians" },
  { value: "tutor", label: "Tutors" },
  { value: "pet", label: "Pets" },
  { value: "volunteer", label: "Volunteers" },
];

export default function DirectoryPage() {
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const { data, error, loading, reload } = useQuery(() => api<DirectoryItem[]>(`/api/directory?${cat ? `category=${cat}&` : ""}${q ? `q=${encodeURIComponent(q)}` : ""}`), [cat, q]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Community Directory</h1>
        <p className="text-muted">Emergency numbers and local services near you.</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Input aria-label="Search the directory" placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} maxLength={80} className="max-w-xs" />
        <div className="max-w-full overflow-x-auto">
          <select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} className="min-h-11 rounded-xl border border-line bg-surface px-3 sm:hidden">
            {CATS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <div className="hidden sm:block"><Segmented label="Category" value={cat} onChange={setCat} options={CATS} /></div>
        </div>
      </div>
      {loading ? <LoadingBlock /> : error ? <ErrorState message={error} onRetry={reload} /> : (data ?? []).length === 0 ? (
        <EmptyState icon="📒" title="Nothing found" body="Try a different category or search." />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {data!.map((e) => (
            <li key={e.id}>
              <Card as="article" className={e.category === "emergency" ? "border-danger/40" : ""}>
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold">{e.name}</p>
                  <Badge tone={e.category === "emergency" ? "danger" : "neutral"}>{e.category}</Badge>
                </div>
                <p className="mt-1 text-sm text-muted">{[e.is_24h ? "Open 24h" : null, e.distance_km != null ? fmtDistance(e.distance_km) : null].filter(Boolean).join(" · ")}</p>
                {e.phone && <a href={`tel:${e.phone.replace(/\s/g, "")}`} className="mt-2 inline-flex min-h-11 items-center gap-2 font-semibold text-brandtext">📞 {e.phone}</a>}
                {e.notes && <p className="mt-1 text-xs text-muted">{e.notes}</p>}
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
