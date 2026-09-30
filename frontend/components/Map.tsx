"use client";
import dynamic from "next/dynamic";
import { Spinner } from "./ui";

export type { MapMarker, MapHeat } from "./MapView";

/** Leaflet touches `window`, so the map is loaded client-side only. */
const Map = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="grid h-72 place-items-center rounded-2xl bg-surface2 text-muted">
      <Spinner />
    </div>
  ),
});
export default Map;
