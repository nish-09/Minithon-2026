"use client";
import { useEffect, useRef, useState } from "react";

// Scene from https://github.com/eryilmazburak/Cursor-Following-3D-Human-Figure (MIT, Burak Eryılmaz).
const SCENE_URL = "https://prod.spline.design/FSIRibZyFy-pmM6r/scene.splinecode";

/** 3D figure whose head follows the cursor. Decorative: if it can't load, nothing is rendered. */
export function NexaAvatar({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let app: { dispose?: () => void } | null = null;

    // The scene only reacts to events on its own canvas, so relay the cursor from the whole window.
    const relay = (e: MouseEvent) => {
      canvas.dispatchEvent(new MouseEvent("mousemove", { clientX: e.clientX, clientY: e.clientY, screenX: e.screenX, screenY: e.screenY }));
    };

    (async () => {
      try {
        const { Application } = await import("@splinetool/runtime");
        if (disposed) return;
        const a = new Application(canvas);
        app = a as unknown as { dispose?: () => void };
        await a.load(SCENE_URL);
        if (disposed) return a.dispose();
        window.addEventListener("mousemove", relay);
      } catch {
        if (!disposed) setFailed(true);
      }
    })();

    return () => {
      disposed = true;
      window.removeEventListener("mousemove", relay);
      app?.dispose?.();
    };
  }, []);

  if (failed) return null;
  return <canvas ref={canvasRef} aria-hidden="true" className={className} />;
}
