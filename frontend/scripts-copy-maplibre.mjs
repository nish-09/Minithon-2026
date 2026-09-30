// Serve MapLibre's CSP worker as a static asset (Turbopack does not bundle it). Runs after npm install.
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("public", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-csp-worker.js", "public/maplibre-gl-csp-worker.js");
