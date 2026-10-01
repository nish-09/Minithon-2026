import type { StyleSpecification } from "maplibre-gl";

/** NEXA's illustrated community-map style with cohesive lavender-pastel geographic colors. */
export const PALETTE = {
  land: "#E8E8EC",
  residential: "#DEDEE4",
  commercial: "#F5E4D9",
  institution: "#F5EDCE", // Community spaces
  park: "#DCECE2",        // Parks / greenery
  water: "#D7EAF5",       // Water
  building: "#D8D8DF",    // Dense urban areas
  roadCasing: "#947FCB",  // Road outlines
  roadMajor: "#B9A8E6",   // Major roads
  roadMid: "#B9A8E6",
  roadMinor: "#F0F0F3",   // Local roads
  boundary: "#C4C4CE",    // Boundaries
  label: "#373342",       // Geographic labels
  labelSecondary: "#777183", // Secondary labels
  halo: "#E8E8EC",
};

const FONT_REG = ["Noto Sans Regular"];
const FONT_BOLD = ["Noto Sans Bold"];

function road(id: string, classes: string[], color: string, widths: [number, number], casing = true) {
  const filter = ["in", "class", ...classes] as unknown as never;
  const w = (k: number) => ["interpolate", ["exponential", 1.4], ["zoom"], 9, widths[0] * 0.3 * k, 14, widths[0] * k, 18, widths[1] * k];
  const layers = [];
  if (casing) {
    layers.push({ id: `${id}-casing`, type: "line", source: "om", "source-layer": "transportation", filter, layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": PALETTE.roadCasing, "line-width": w(1.5) } });
  }
  layers.push({ id, type: "line", source: "om", "source-layer": "transportation", filter, layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": color, "line-width": w(1) } });
  return layers;
}

export const nexaMapStyle = {
  version: 8,
  // true 3D globe when zoomed out, blending to the flat street map at city zoom
  projection: { type: ["interpolate", ["linear"], ["zoom"], 8, "vertical-perspective", 11, "mercator"] },
  sky: {
    "sky-color": "#C9BDF0", "horizon-color": "#E8E8EC", "fog-color": "#E8E8EC",
    "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.4,
    "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 8, 1, 12, 0],
  },
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: { om: { type: "vector", url: "https://tiles.openfreemap.org/planet" } },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": PALETTE.land } },
    { id: "landuse-res", type: "fill", source: "om", "source-layer": "landuse", filter: ["in", "class", "residential", "suburb", "neighbourhood"], paint: { "fill-color": PALETTE.residential } },
    { id: "landuse-commercial", type: "fill", source: "om", "source-layer": "landuse", filter: ["in", "class", "commercial", "retail", "industrial"], paint: { "fill-color": PALETTE.commercial, "fill-opacity": 0.75 } },
    { id: "landuse-institution", type: "fill", source: "om", "source-layer": "landuse", filter: ["in", "class", "hospital", "school", "university", "college", "kindergarten"], paint: { "fill-color": PALETTE.institution } },
    { id: "landcover", type: "fill", source: "om", "source-layer": "landcover", filter: ["in", "class", "grass", "wood", "farmland"], paint: { "fill-color": PALETTE.park, "fill-opacity": 0.85 } },
    { id: "landuse-green", type: "fill", source: "om", "source-layer": "landuse", filter: ["in", "class", "cemetery", "playground", "pitch", "stadium"], paint: { "fill-color": PALETTE.park, "fill-opacity": 0.8 } },
    { id: "park", type: "fill", source: "om", "source-layer": "park", paint: { "fill-color": PALETTE.park } },
    { id: "water", type: "fill", source: "om", "source-layer": "water", paint: { "fill-color": PALETTE.water } },
    { id: "waterway", type: "line", source: "om", "source-layer": "waterway", paint: { "line-color": PALETTE.water, "line-width": 2 } },
    { id: "building", type: "fill", source: "om", "source-layer": "building", minzoom: 14, paint: { "fill-color": PALETTE.building, "fill-opacity": 0.9 } },
    { id: "boundary", type: "line", source: "om", "source-layer": "boundary", paint: { "line-color": PALETTE.boundary, "line-width": 1 } },
    ...road("road-minor", ["minor", "service", "path", "track"], PALETTE.roadMinor, [3, 9]),
    ...road("road-mid", ["tertiary", "secondary"], PALETTE.roadMid, [4, 13]),
    ...road("road-major", ["primary", "trunk", "motorway"], PALETTE.roadMajor, [5, 16]),
    { id: "road-name", type: "symbol", source: "om", "source-layer": "transportation_name", minzoom: 15, layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": FONT_REG, "text-size": 11 }, paint: { "text-color": PALETTE.labelSecondary, "text-halo-color": PALETTE.halo, "text-halo-width": 1.5 } },
    { id: "water-name", type: "symbol", source: "om", "source-layer": "water_name", layout: { "text-field": ["get", "name"], "text-font": FONT_REG, "text-size": 12, "text-letter-spacing": 0.1 }, paint: { "text-color": "#285C7C", "text-halo-color": PALETTE.halo, "text-halo-width": 1.5 } },
    { id: "place-major", type: "symbol", source: "om", "source-layer": "place", filter: ["in", "class", "city", "town", "suburb"], layout: { "text-field": ["get", "name"], "text-font": FONT_BOLD, "text-size": ["interpolate", ["linear"], ["zoom"], 8, 12, 14, 16], "text-transform": "uppercase", "text-letter-spacing": 0.08 }, paint: { "text-color": PALETTE.label, "text-halo-color": PALETTE.halo, "text-halo-width": 2 } },
    { id: "place-minor", type: "symbol", source: "om", "source-layer": "place", filter: ["in", "class", "neighbourhood", "village", "quarter"], layout: { "text-field": ["get", "name"], "text-font": FONT_REG, "text-size": 12 }, paint: { "text-color": PALETTE.labelSecondary, "text-halo-color": PALETTE.halo, "text-halo-width": 1.5 } },
  ],
} as unknown as StyleSpecification;
