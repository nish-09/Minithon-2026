"use client";
import Link from "next/link";
import { useEffect } from "react";
import { Card, EmptyState, ErrorState, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import type { NotificationItem } from "@/lib/types";

function href(n: NotificationItem): string | null {
  if (n.data?.incident_id) return `/care/${n.data.incident_id}`;
  if (n.data?.request_id) return `/requests/${n.data.request_id}`;
  if (n.kind.startsWith("relationship")) return "/circle";
  return null;
}

export default function NotificationsPage() {
  const { data, error, loading, reload } = useQuery(() => api<{ unread: number; items: NotificationItem[] }>("/api/notifications?limit=100"), []);
  useLiveEvents((e) => e.type === "notification" && void reload());
  // mark as read a moment after they're shown, keeping the "new" styling for this visit
  useEffect(() => {
    if (data && data.unread > 0) {
      const t = setTimeout(() => void api("/api/notifications/read", { method: "POST" }).catch(() => undefined), 1500);
      return () => clearTimeout(t);
    }
  }, [data]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Notifications</h1>
      {loading ? <LoadingBlock /> : error ? <ErrorState message={error} onRetry={reload} /> : (data?.items.length ?? 0) === 0 ? (
        <EmptyState icon="🔔" title="You're all caught up" body="Updates about your requests and Trusted Circle appear here." />
      ) : (
        <ul className="space-y-2">
          {data!.items.map((n) => {
            const link = href(n);
            const inner = (
              <Card className={`!p-4 ${!n.read ? "border-brand/50 bg-brandsoft/40" : ""}`}>
                <div className="flex justify-between gap-3">
                  <p className="font-semibold">{n.title}</p>
                  <span className="shrink-0 text-xs text-muted">{timeAgo(n.created_at)}</span>
                </div>
                {n.body && <p className="mt-0.5 text-sm text-muted">{n.body}</p>}
              </Card>
            );
            return <li key={n.id}>{link ? <Link href={link}>{inner}</Link> : inner}</li>;
          })}
        </ul>
      )}
    </div>
  );
}
