"use client";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useQuery } from "@/lib/hooks";
import { useLiveEvents } from "@/lib/realtime";
import { Button, Card, ErrorState, Input, LoadingBlock, SectionTitle, cx } from "./ui";

interface Msg {
  id: number;
  sender_id: number;
  sender: string | null;
  body: string;
  created_at: string;
}

export function ChatPanel({ requestId, disabled }: { requestId: number; disabled?: boolean }) {
  const { user } = useAuth();
  const { data, error, loading, reload, setData } = useQuery(() => api<Msg[]>(`/api/requests/${requestId}/messages`), [requestId]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useLiveEvents((e) => {
    if (e.type === "message" && e.request_id === requestId) void reload();
  }, [requestId]);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [data?.length]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (!body) return;
    setSending(true);
    setSendError(null);
    try {
      const m = await api<Msg>(`/api/requests/${requestId}/messages`, { method: "POST", body: { body } });
      setData((d) => [...(d ?? []), { ...m, sender: user?.name ?? null }]);
      setText("");
    } catch (err) {
      setSendError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <SectionTitle>Chat</SectionTitle>
      {loading ? (
        <LoadingBlock />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <>
          <div className="max-h-64 space-y-2 overflow-y-auto" aria-live="polite" aria-label="Messages">
            {data!.length === 0 && <p className="py-4 text-center text-sm text-muted">No messages yet. Say hello 👋</p>}
            {data!.map((m) => (
              <div key={m.id} className={cx("max-w-[85%] rounded-2xl px-3.5 py-2 text-sm", m.sender_id === user?.id ? "ml-auto bg-brand text-brandink" : "bg-surface2")}>
                {m.sender_id !== user?.id && <p className="text-[11px] font-semibold opacity-70">{m.sender?.split(" ")[0]}</p>}
                {m.body}
              </div>
            ))}
            <div ref={end} />
          </div>
          {!disabled && (
            <form onSubmit={send} className="mt-3 flex gap-2">
              <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder="Write a message…" aria-label="Message" />
              <Button type="submit" loading={sending} disabled={!text.trim()}>
                Send
              </Button>
            </form>
          )}
          {sendError && <p role="alert" className="mt-2 text-sm text-danger">{sendError}</p>}
        </>
      )}
    </Card>
  );
}
