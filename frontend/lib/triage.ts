export interface TriageResult {
  level: "LOW" | "MODERATE" | "URGENT" | "CRITICAL";
  summary: string;
  reasons: string[];
  red_flags: string[];
  observed: string[];
  inferred: string[];
  unknown: string[];
  questions: { key: string; text: string }[];
  steps: { key: string; icon: string; text: string }[];
  call_emergency: boolean;
  notify_circle: boolean;
  limits: string;
  suggest_visual: boolean;
}

/* what the person (or an optional camera frame) can report as visible; keys match backend OBSERVATIONS */
export const VISIBLE_SIGNS: [string, string][] = [
  ["heavy_bleeding", "Heavy bleeding"],
  ["bleeding", "Bleeding"],
  ["open_wound", "Open wound"],
  ["swelling", "Swelling"],
  ["bruising", "Bruising"],
  ["redness", "Redness"],
  ["burn", "Possible burn"],
  ["deformity", "Unusual shape or position of a limb"],
  ["foreign_object", "Object stuck in the wound"],
  ["cannot_move_part", "Can't move the affected part"],
  ["unresponsive", "Person is not responding"],
];

/* mirrors backend triage.TRIGGER: an injury or emergency described in conversation */
export const TRIGGER_RE = /\b(fell|fall|fallen|bleed\w*|blood|burn\w*|scald\w*|swollen|swelling|hit my head|head injury|unconscious|unresponsive|can'?t move|cannot move|got cut|cut my|chest (hurts|pain)|trouble breathing|can'?t breathe|difficulty breathing|injur\w+|broke\w*|sprain\w*|seizure|collapsed|choking|allergic)\b/i;
