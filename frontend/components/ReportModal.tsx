"use client";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useToast } from "@/lib/hooks";
import { Button, Field, Modal, Textarea } from "./ui";

export function ReportModal({ userId, requestId, onClose }: { userId: number | null; requestId?: number; onClose: () => void }) {
  const toast = useToast();
  const [reason, setReason] = useState("unsafe");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={userId !== null} onClose={onClose} title="Report a problem">
      <div className="space-y-3">
        <Field label="What happened?">{(id) => (
          <select id={id} value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5">
            {["unsafe", "harassment", "no_show", "fraud", "spam", "other"].map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
          </select>
        )}</Field>
        <Field label="Details">{(id) => <Textarea id={id} rows={4} maxLength={2000} value={details} onChange={(e) => setDetails(e.target.value)} />}</Field>
        <p className="text-xs text-muted">Reports are reviewed by NEXA administrators. The person is not told who reported.</p>
        <Button className="w-full" loading={busy} onClick={async () => {
          setBusy(true);
          try { await api("/api/reports", { method: "POST", body: { target_user_id: userId, request_id: requestId, reason, details } }); toast.push({ kind: "success", title: "Report sent" }); onClose(); }
          catch (e) { toast.push({ kind: "error", title: "Couldn't send report", body: errorMessage(e) }); }
          finally { setBusy(false); }
        }}>Send report</Button>
      </div>
    </Modal>
  );
}
