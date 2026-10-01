"use client";
import { Camera, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cameraErrorMessage, openCameraStream, photoFromVideo, type Photo } from "@/lib/image";

/** Live camera sheet for NEXA: the preview stays on the device; only the captured still can be sent, and only when the person sends it. */
export function NexaCamera({ onCapture, onClose }: { onCapture: (p: Photo) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    openCameraStream().then(
      (s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        const v = videoRef.current;
        if (v) { v.srcObject = s; void v.play().catch(() => {}); }
      },
      (e) => !cancelled && setErr(cameraErrorMessage(e)),
    );
    const t = setTimeout(() => { if (!cancelled && !videoRef.current?.videoWidth) setErr("The camera is on but no picture is coming through. Check its privacy shutter and that no other app is using it, or upload a photo instead."); }, 5000);
    return () => { cancelled = true; clearTimeout(t); stream?.getTracks().forEach((x) => x.stop()); };
  }, []);

  function capture() {
    const v = videoRef.current;
    const p = v && photoFromVideo(v);
    if (p) onCapture(p);
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Take a photo" className="absolute inset-0 z-40 grid place-items-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="rise nexa-glass w-full max-w-md space-y-3 rounded-3xl p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold">Take a photo</h2>
          <button type="button" onClick={onClose} aria-label="Close camera" className="grid h-9 w-9 place-items-center rounded-full hover:bg-white/10"><X aria-hidden size={18} /></button>
        </div>
        {err ? (
          <p role="alert" className="rounded-2xl bg-white/10 p-4 text-sm">{err}</p>
        ) : (
          <video ref={videoRef} autoPlay muted playsInline onLoadedMetadata={() => setReady(true)} aria-label="Camera preview. It stays on this device." className="aspect-[4/3] w-full rounded-2xl bg-black object-cover" />
        )}
        <p className="text-xs text-white/70">The preview stays on your device. A picture is only sent when you press Send.</p>
        <div className="flex gap-2">
          <button type="button" onClick={capture} disabled={!ready || !!err} className="clay-btn flex min-h-12 flex-1 items-center justify-center gap-2 !rounded-full bg-brand font-bold text-brandink disabled:opacity-40">
            <Camera aria-hidden size={18} /> Capture
          </button>
          <button type="button" onClick={onClose} className="min-h-12 rounded-full border border-white/30 px-5 text-sm font-semibold hover:bg-white/10">Cancel</button>
        </div>
      </div>
    </div>
  );
}
