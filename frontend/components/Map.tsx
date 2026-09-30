"use client";
import dynamic from "next/dynamic";
import { Spinner } from "./ui";

export type { MapMarker, MapHeat, MarkerKind } from "./MapView";

/** MapLibre touches `window`, so the map is loaded client-side only. */
const Map = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="clay-well grid h-72 place-items-center text-muted">
      <Spinner />
    </div>
  ),
});
export default Map;
