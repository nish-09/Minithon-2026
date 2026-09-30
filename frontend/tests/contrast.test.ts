import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/* Verifies the Bright Claymorphism tokens themselves meet WCAG 2.2 AA, so a palette tweak can't silently break contrast.
   Text pairs need 4.5:1, UI-component pairs 3:1. Shadows and gradients are never part of the check.
   `--faint` (#71809a) is intentionally NOT asserted: it is below AA and may only decorate, never carry meaning. */
const css = readFileSync(path.join(__dirname, "../app/globals.css"), "utf-8");
const root = css.slice(css.indexOf(":root"), css.indexOf("@theme"));
const raw: Record<string, string> = {};
for (const m of root.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6}|var\(--[a-z0-9-]+\))/g)) raw[m[1]] = m[2];
function resolve(name: string): string {
  if (name.startsWith("#")) return name;
  let v = raw[name];
  while (v && v.startsWith("var(")) v = raw[v.slice(6, -1)];
  if (!v) throw new Error(`unknown token ${name}`);
  return v;
}

function lum(hex: string) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function ratio(a: string, b: string) {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const TEXT: [string, string, string][] = [
  ["ink", "surface", "primary text on neutral clay"], ["ink", "bg", "primary text on the page"], ["ink", "bg-alt", "primary text on supporting page tone"], ["ink", "surface-2", "text in wells/inputs"],
  ["muted", "surface", "secondary text on clay"], ["muted", "bg", "secondary text on the page"], ["muted", "surface-2", "secondary text in wells"],
  ["ink", "lavender", "primary button"], ["ink", "yellow", "highlight button / yellow card"], ["ink", "mint", "success button / mint badge"], ["ink", "peach", "error badge"], ["ink", "sky", "info badge"],
  ["muted", "yellow", "secondary text on yellow card"], ["muted", "mint", "secondary text on mint card"], 
  ["brand-text", "surface", "links on clay"], ["brand-text", "bg", "links on page"], ["brand-text", "brand-soft", "selected text on soft lavender"],
  ["ok", "surface", "success text"], ["ok", "bg", "success text on page"], ["warn", "surface", "warning text"], ["warn", "bg", "warning text on page"],
  ["danger", "surface", "error text"], ["danger", "bg", "error text on page"], ["accent", "surface", "info text"],
  ["#ffffff", "danger-solid", "SOS / destructive button label"], ["#ffffff", "ok-solid", "filled success label"], ["#ffffff", "warn-solid", "filled warning label"],
  ["#ffffff", "#8f1111", "emergency button label"], ["#1a0000", "#ffffff", "emergency panel text"], ["#ffffff", "#7f0f0f", "emergency status strip"],
];
const UI: [string, string, string][] = [
  ["line-strong", "surface", "control border on clay"], ["line-strong", "bg", "control border on page"], ["line-strong", "surface-2", "toggle-off border on well"],
  ["focus", "surface", "focus ring on clay"], ["focus", "bg", "focus ring on page"], ["focus", "focus-halo", "focus ring vs its white halo"], ["focus", "#ffffff", "focus ring on emergency panels"],
  ["ok", "surface", "success icon"], ["danger", "surface", "danger icon"], ["warn", "surface", "warning icon"], ["#4a2fb0", "surface-2", "input focus border"],
];

describe("Bright Claymorphism tokens meet WCAG 2.2 AA", () => {
  it("uses the specified palette", () => {
    expect([resolve("bg"), resolve("lavender"), resolve("yellow"), resolve("mint"), resolve("peach"), resolve("sky")]).toEqual(["#ddebff", "#c9a7ff", "#ffe58a", "#9ff3d0", "#ffb8a8", "#9dd9ff"]);
    expect([resolve("ink"), resolve("muted")]).toEqual(["#172033", "#526078"]);
  });
  it.each(TEXT)("text %s on %s >= 4.5:1 (%s)", (fg, bg) => {
    expect(ratio(resolve(fg), resolve(bg))).toBeGreaterThanOrEqual(4.5);
  });
  it.each(UI)("UI %s vs %s >= 3:1 (%s)", (fg, bg) => {
    expect(ratio(resolve(fg), resolve(bg))).toBeGreaterThanOrEqual(3);
  });
  it("saturated pastel surfaces promote secondary text to ink", () => {
    expect(css).toMatch(/\.tone-lavender, \.tone-sky, \.tone-peach \{ --muted: var\(--ink\); \}/);
    expect(ratio(resolve("ink"), resolve("lavender"))).toBeGreaterThanOrEqual(4.5);
  });
  it("critical emergency text is stronger than AA (>= 7:1)", () => {
    expect(ratio("#1a0000", "#ffffff")).toBeGreaterThanOrEqual(7);
    expect(ratio("#ffffff", "#7f0f0f")).toBeGreaterThanOrEqual(7);
    expect(ratio("#ffffff", "#8f1111")).toBeGreaterThanOrEqual(7);
  });
});
