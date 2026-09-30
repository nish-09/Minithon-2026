"use client";
import { STATUS_LABEL, timeAgo } from "@/lib/format";
import type { HelpRequest } from "@/lib/types";
import { cx } from "./ui";

/** Happy-path steps shown as a progress rail; terminal/alternate states are shown as a banner instead. */
const RAIL = ["MATCHING", "TRUSTED_CIRCLE", "HELPERS_NOTIFIED", "ACCEPTED", "ON_THE_WAY", "IN_PROGRESS", "COMPLETED", "RATED"] as const;
const RAIL_LABEL: Record<string, string> = {
  MATCHING: "Understood",
  TRUSTED_CIRCLE: "Trusted Circle",
  HELPERS_NOTIFIED: "Helpers notified",
  ACCEPTED: "Accepted",
  ON_THE_WAY: "On the way",
  IN_PROGRESS: "Helping",
  COMPLETED: "Completed",
  RATED: "Rated",
};

export function StatusTimeline({ req }: { req: HelpRequest }) {
  const visited = new Set((req.history ?? []).map((h) => h.to));
  const current = req.status === "ASSIGNED" ? "ACCEPTED" : req.status === "ESCALATED" ? "HELPERS_NOTIFIED" : req.status;
  const idx = RAIL.indexOf(current as (typeof RAIL)[number]);
  const closed = ["CANCELLED", "EXPIRED"].includes(req.status);
  const skippedCircle = !visited.has("TRUSTED_CIRCLE");
  const steps = RAIL.filter((s) => !(s === "TRUSTED_CIRCLE" && skippedCircle));

  return (
    <div>
      {closed && (
        <div role="status" className="mb-3 rounded-xl bg-dangersoft px-4 py-2.5 text-sm font-semibold">
          {STATUS_LABEL[req.status]}
        </div>
      )}
      <ol className="flex items-start gap-1 overflow-x-auto pb-1" aria-label="Request progress">
        {steps.map((s) => {
          const i = RAIL.indexOf(s);
          const done = !closed && (i < idx || (idx === -1 && false));
          const active = !closed && s === current;
          return (
            <li key={s} aria-current={active ? "step" : undefined} className="flex min-w-[68px] flex-1 flex-col items-center text-center">
              <span className={cx("grid h-8 w-8 place-items-center rounded-full border-2 text-xs font-bold transition", done ? "border-ok bg-oksolid text-white" : active ? "border-brand bg-brand text-brandink pulse-ring" : "border-line text-muted")}>{done ? "✓" : i + 1}</span>
              <span className={cx("mt-1.5 text-[11px] leading-tight", active ? "font-semibold" : "text-muted")}>{RAIL_LABEL[s]}</span>
            </li>
          );
        })}
      </ol>
      {req.history && req.history.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Activity log</summary>
          <ul className="mt-2 space-y-1">
            {[...req.history].reverse().map((h, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span>
                  {STATUS_LABEL[h.to] ?? h.to}
                  {h.note ? <span className="text-muted"> · {h.note}</span> : null}
                </span>
                <span className="shrink-0 text-muted">{timeAgo(h.at)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
