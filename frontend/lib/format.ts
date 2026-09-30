export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtDistance(km: number | null | undefined): string {
  if (km == null) return "";
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

export function fmtEta(min: number | null | undefined): string {
  if (min == null) return "";
  return min < 1.5 ? "1 min" : `${Math.round(min)} min`;
}

export function fmtCountdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${Math.round(seconds / 60)} min`;
}

export const STATUS_LABEL: Record<string, string> = {
  CREATED: "Created",
  ANALYZING: "Understanding your request",
  MATCHING: "Finding the right help",
  TRUSTED_CIRCLE: "Asking your Trusted Circle",
  HELPERS_NOTIFIED: "Helpers notified",
  ASSIGNED: "Helper assigned",
  ACCEPTED: "Helper accepted",
  ON_THE_WAY: "Helper on the way",
  IN_PROGRESS: "Helping now",
  COMPLETED: "Completed",
  RATED: "Completed & rated",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
  ESCALATED: "Widening to community",
};

export const LIFECYCLE = ["CREATED", "ANALYZING", "MATCHING", "TRUSTED_CIRCLE", "HELPERS_NOTIFIED", "ASSIGNED", "ACCEPTED", "ON_THE_WAY", "IN_PROGRESS", "COMPLETED", "RATED"];

export const CLOSED_STATUSES = ["COMPLETED", "RATED", "CANCELLED", "EXPIRED"];

export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 5 ? "Hello" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : h < 22 ? "Good evening" : "Hello";
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
