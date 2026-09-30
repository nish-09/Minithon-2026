"use client";
import * as maplibregl from "maplibre-gl/dist/maplibre-gl-csp";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { nexaMapStyle } from "@/lib/mapStyle";

/** Marker kinds differ by SHAPE + ICON + TEXT label + colour, so none of them relies on colour alone. */
export type MarkerKind = "me" | "request" | "urgent" | "critical" | "helper" | "circle" | "service" | "event";
export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  kind: MarkerKind;
  icon?: string; // supporting glyph/emoji
  label?: string;
  detail?: string;
  onClick?: () => void;
}
export interface MapHeat {
  lat: number;
  lng: number;
  weight: number; // 0..1
  label?: string;
}

const KIND: Record<MarkerKind, { shape: string; color: string; iconColor?: string; glyph: string; name: string; tag?: string }> = {
  me: { shape: "pin", color: "#F2DCA6", iconColor: "#76531D", glyph: "●", name: "Your location", tag: "YOU" },
  request: { shape: "circle", color: "#F4B7A8", iconColor: "#793C35", glyph: "?", name: "Help request" },
  urgent: { shape: "diamond", color: "#a84300", iconColor: "#ffffff", glyph: "!", name: "Urgent request", tag: "URGENT" },
  critical: { shape: "octagon", color: "#a51818", iconColor: "#ffffff", glyph: "!", name: "Critical incident", tag: "CRITICAL" },
  helper: { shape: "square", color: "#B5DEC9", iconColor: "#17633F", glyph: "✓", name: "Available helper" },
  circle: { shape: "star", color: "#D6C2F1", iconColor: "#613A96", glyph: "♥", name: "Trusted Circle member" },
  service: { shape: "hex", color: "#B7DDF2", iconColor: "#285C7C", glyph: "+", name: "Community service" },
  event: { shape: "square", color: "#D6C2F1", iconColor: "#613A96", glyph: "★", name: "Community activity" },
};

function markerEl(m: MapMarker): HTMLButtonElement {
  const k = KIND[m.kind];
  const b = document.createElement("button");
  b.type = "button";
  b.className = "nexa-marker";
  b.setAttribute("aria-label", `${k.name}${m.label ? `: ${m.label}` : ""}${m.detail ? `. ${m.detail}` : ""}`);
  const shape = document.createElement("span");
  shape.className = `shape shape-${k.shape}`;
  shape.style.background = k.color;
  shape.style.color = k.iconColor || "#fff";
  const icon = document.createElement("span");
  icon.textContent = m.kind === "request" || m.kind === "service" || m.kind === "event" ? (m.icon ?? k.glyph) : k.glyph;
  icon.setAttribute("aria-hidden", "true");
  shape.appendChild(icon);
  b.appendChild(shape);
  if (k.tag) {
    const t = document.createElement("span");
    t.className = "tag";
    t.textContent = k.tag;
    t.setAttribute("aria-hidden", "true");
    b.appendChild(t);
  }
  return b;
}

function ring(lat: number, lng: number, km: number) {
  const pts: [number, number][] = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * 2 * Math.PI;
    pts.push([lng + (km / (111 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a), lat + (km / 111) * Math.sin(a)]);
  }
  return { type: "Feature" as const, properties: {}, geometry: { type: "Polygon" as const, coordinates: [pts] } };
}

maplibregl.setWorkerUrl("/maplibre-gl-csp-worker.js");

export default function MapView({
  center,
  zoom = 14,
  markers = [],
  heat = [],
  radiusKm,
  fitToMarkers,
  className = "h-72",
  label = "Map",
}: {
  center: [number, number]; // [lat, lng]
  zoom?: number;
  markers?: MapMarker[];
  heat?: MapHeat[];
  radiusKm?: number;
  fitToMarkers?: boolean;
  className?: string;
  label?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const live = useRef<maplibregl.Marker[]>([]);
  const [ready, setReady] = useState(false);
  const [tilesFailed, setTilesFailed] = useState(false);
  const [popupText, setPopupText] = useState("");

  useEffect(() => {
    if (!box.current) return;
    const map = new maplibregl.Map({ container: box.current, style: nexaMapStyle, center: [center[1], center[0]], zoom, attributionControl: { compact: true }, canvasContextAttributes: { preserveDrawingBuffer: true } });
    mapRef.current = map;
    map.on("load", () => {
      map.addSource("ring", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "ring-fill", type: "fill", source: "ring", paint: { "fill-color": "#5b34d6", "fill-opacity": 0.05 } });
      map.addLayer({ id: "ring-line", type: "line", source: "ring", paint: { "line-color": "#5b34d6", "line-width": 2, "line-dasharray": [2, 2] } });
      map.addSource("heat", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "heat", type: "circle", source: "heat",
        paint: {
          "circle-radius": ["+", 12, ["*", 28, ["get", "w"]]],
          "circle-color": ["interpolate", ["linear"], ["get", "w"], 0, "#ffd9b8", 0.5, "#f59f7b", 1, "#b23a6b"],
          "circle-opacity": 0.65, "circle-stroke-color": "#4b1d3f", "circle-stroke-width": 1.5,
        },
      });
      setReady(true);
    });
    map.on("error", (e: maplibregl.ErrorEvent) => {
      console.warn("[nexa-map]", e.error?.message ?? e);
      if (String(e.error?.message ?? "").match(/Failed to fetch|tile|NetworkError/i)) setTilesFailed(true);
    });
    const t = setTimeout(() => map.resize(), 250);
    return () => {
      clearTimeout(t);
      live.current.forEach((m) => m.remove());
      live.current = [];
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // the map instance is created once; data effects below keep it in sync
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // recentre / fit
  const key = markers.map((m) => m.id).join(",");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (fitToMarkers && markers.length > 1) {
      const b = new maplibregl.LngLatBounds();
      markers.forEach((m) => b.extend([m.lng, m.lat]));
      map.fitBounds(b as LngLatBoundsLike, { padding: 60, maxZoom: 16, duration: 0 });
    } else {
      map.jumpTo({ center: [center[1], center[0]], zoom });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center[0], center[1], zoom, fitToMarkers, key, ready]);

  // markers (DOM buttons: keyboard focusable, labelled)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    live.current.forEach((m) => m.remove());
    live.current = markers.map((m) => {
      const el = markerEl(m);
      el.addEventListener("click", () => {
        setPopupText([KIND[m.kind].name, m.label, m.detail].filter(Boolean).join(" · "));
        m.onClick?.();
      });
      return new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat([m.lng, m.lat]).addTo(map);
    });
  }, [markers, ready]);

  // heat + radius
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("heat") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: heat.map((h) => ({ type: "Feature", properties: { w: h.weight, label: h.label ?? "" }, geometry: { type: "Point", coordinates: [h.lng, h.lat] } })),
    });
    (map.getSource("ring") as GeoJSONSource).setData({ type: "FeatureCollection", features: radiusKm ? [ring(center[0], center[1], radiusKm)] : [] });
  }, [heat, radiusKm, center, ready]);

  const btn = "clay-btn clay-btn-secondary grid h-11 w-11 place-items-center text-xl";
  return (
    <div className={`relative ${className}`} role="region" aria-label={label}>
      <div ref={box} className="h-full w-full" />
      {/* Map controls use the same clay system as the rest of NEXA */}
      <div className="absolute left-3 top-3 z-10 flex flex-col gap-2">
        <button type="button" className={btn} aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()}><span aria-hidden>＋</span></button>
        <button type="button" className={btn} aria-label="Zoom out" onClick={() => mapRef.current?.zoomOut()}><span aria-hidden>－</span></button>
        <button type="button" className={btn} aria-label="Recenter map" onClick={() => mapRef.current?.easeTo({ center: [center[1], center[0]], zoom })}><span aria-hidden>◎</span></button>
      </div>
      {popupText && (
        <div role="status" className="clay-card absolute inset-x-3 bottom-8 z-10 flex items-center gap-2 !rounded-2xl px-4 py-2 text-sm font-bold sm:inset-x-auto sm:left-16 sm:max-w-sm">
          <span className="min-w-0 flex-1">{popupText}</span>
          <button type="button" onClick={() => setPopupText("")} aria-label="Dismiss details" className="grid h-11 w-11 place-items-center"><span aria-hidden>✕</span></button>
        </div>
      )}
      {tilesFailed && <p role="status" className="absolute right-3 top-3 z-10 rounded-xl border-2 border-warn bg-warnsoft px-3 py-1 text-xs font-bold text-warn">▲ Map tiles unavailable. Markers still shown.</p>}
    </div>
  );
}
