import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { PALETTE, nexaMapStyle } from "@/lib/mapStyle";

describe("NEXA custom map style", () => {
  it("is a valid MapLibre style (no spec errors)", () => {
    const errors = validateStyleMin(nexaMapStyle as never);
    expect(errors.map((e) => `${e.identifier ?? ""} ${e.message}`)).toEqual([]);
  });

  it("uses the pastel community palette, not a conventional navigation look", () => {
    expect(PALETTE.land).toBe("#f4efff"); // lavender/cream land
    expect(PALETTE.water).toBe("#bde0f3"); // pastel blue
    expect(PALETTE.park).toBe("#cfe5cf"); // pastel sage
    expect(PALETTE.label).toBe("#2b2046"); // dark plum labels
    expect(new Set(nexaMapStyle.layers.map((l) => l.id)).size).toBe(nexaMapStyle.layers.length); // unique ids
  });

  it("keeps labels minimal (no POI layer)", () => {
    expect(nexaMapStyle.layers.some((l) => (l as { "source-layer"?: string })["source-layer"] === "poi")).toBe(false);
  });
});

describe("map safety", () => {
  it("never renders HTML into the map (maplibre-gl 5 has an advisory on Popup.setHTML sanitising)", async () => {
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(`${__dirname}/../components/MapView.tsx`, "utf-8");
    expect(src).not.toMatch(/setHTML|\.innerHTML|maplibregl\.Popup|new Popup/);
  });
});
