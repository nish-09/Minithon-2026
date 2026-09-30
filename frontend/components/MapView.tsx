"use client";
import L from "leaflet";
import { useEffect } from "react";
import { Circle, CircleMarker, MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  emoji: string;
  color: string;
  label?: string;
  detail?: string;
  pulse?: boolean;
  onClick?: () => void;
}
export interface MapHeat {
  lat: number;
  lng: number;
  weight: number; // 0..1
  label?: string;
}

function icon(m: MapMarker) {
  return L.divIcon({
    className: "",
    iconSize: [34, 34],
    iconAnchor: [17, 34],
    popupAnchor: [0, -30],
    html: `<div class="nexa-pin ${m.pulse ? "pulse-ring" : ""}" style="background:${m.color}"><span>${m.emoji}</span></div>`,
  });
}

function Recenter({ center, zoom, fit }: { center: [number, number]; zoom: number; fit?: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (fit && fit.length > 1) map.fitBounds(L.latLngBounds(fit), { padding: [40, 40], maxZoom: 16 });
    else map.setView(center, zoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center[0], center[1], zoom, fit?.length]);
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 200); // correct size after layout/animation
    return () => clearTimeout(t);
  }, [map]);
  return null;
}

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
  center: [number, number];
  zoom?: number;
  markers?: MapMarker[];
  heat?: MapHeat[];
  radiusKm?: number;
  fitToMarkers?: boolean;
  className?: string;
  label?: string;
}) {
  const fit = fitToMarkers ? markers.map((m) => [m.lat, m.lng] as [number, number]) : undefined;
  return (
    <div className={className} role="region" aria-label={label}>
      <MapContainer center={center} zoom={zoom} scrollWheelZoom className="h-full w-full">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Recenter center={center} zoom={zoom} fit={fit} />
        {radiusKm && <Circle center={center} radius={radiusKm * 1000} pathOptions={{ color: "#4f46e5", weight: 1, fillOpacity: 0.04, dashArray: "4 6" }} />}
        {heat.map((h, i) => (
          <CircleMarker key={i} center={[h.lat, h.lng]} radius={10 + h.weight * 26} pathOptions={{ color: "#dc2626", weight: 0, fillColor: "#ef4444", fillOpacity: 0.12 + h.weight * 0.5 }}>
            {h.label && <Popup>{h.label}</Popup>}
          </CircleMarker>
        ))}
        {markers.map((m) => (
          <Marker key={m.id} position={[m.lat, m.lng]} icon={icon(m)} eventHandlers={m.onClick ? { click: m.onClick } : undefined} keyboard title={m.label}>
            {(m.label || m.detail) && (
              <Popup>
                <b>{m.label}</b>
                {m.detail && <div>{m.detail}</div>}
              </Popup>
            )}
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
