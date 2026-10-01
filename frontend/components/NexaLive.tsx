"use client";
import { Eye, VideoOff } from "lucide-react";
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { cameraErrorMessage, openCameraStream, photoFromVideo, type Photo } from "@/lib/image";

/** Live camera view for NEXA. The picture stays on the device; NEXA only reads a single still frame when asked
    (each time you speak, or when you press "Look now"). `frameRef` hands that grab to the parent. */
export function NexaLive({ frameRef, looking, onLook, onStop, onFail }: {
  frameRef: MutableRefObject<(() => Photo | null) | null>;
  looking: boolean;
  onLook: () => void;
  onStop: () => void;
  onFail: (message: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const failRef = useRef(onFail);
  useEffect(() => { failRef.current = onFail; });

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    frameRef.current = () => (videoRef.current ? photoFromVideo(videoRef.current) : null);
    openCameraStream().then(
      (s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        const v = videoRef.current;
        if (v) { v.srcObject = s; void v.play().catch(() => {}); }
        s.getVideoTracks()[0]?.addEventListener("ended", () => !cancelled && failRef.current("The camera stopped. Another app may be using it."));
      },
      (e) => !cancelled && failRef.current(cameraErrorMessage(e)),
    );
    const t = setTimeout(() => { if (!cancelled && !videoRef.current?.videoWidth) failRef.current("The camera is on but no picture is coming through. Check its privacy shutter and that no other app is using it."); }, 6000);
    return () => { cancelled = true; clearTimeout(t); frameRef.current = null; stream?.getTracks().forEach((x) => x.stop()); };
  }, [frameRef]);

  return (
    <section aria-label="Live camera" className="rise nexa-glass absolute right-3 top-[4.5rem] z-10 w-44 overflow-hidden rounded-3xl p-1.5 sm:right-6 sm:top-20 sm:w-60">
      <div className="relative">
        <video ref={videoRef} autoPlay muted playsInline onLoadedMetadata={() => setReady(true)} aria-label="Your live camera. It stays on this device." className="aspect-[4/3] w-full rounded-[1.1rem] bg-black object-cover" />
        <span role="status" className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-bold tracking-wider">
          <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" /> LIVE
        </span>
        {looking && <span className="absolute inset-x-0 bottom-0 rounded-b-[1.1rem] bg-black/60 py-1 text-center text-[11px] font-semibold">NEXA is looking…</span>}
      </div>
      <p className="px-2 pt-1.5 text-[11px] leading-snug text-ink/70">NEXA looks at one frame each time you speak. Frames aren&apos;t saved.</p>
      <div className="flex gap-1.5 p-1.5">
        <button type="button" onClick={onLook} disabled={!ready || looking} className="flex min-h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-brand text-xs font-bold text-brandink transition disabled:opacity-40">
          <Eye aria-hidden size={14} /> Look now
        </button>
        <button type="button" onClick={onStop} aria-label="Stop live camera" title="Stop live camera" className="grid h-9 w-9 place-items-center rounded-full border border-white/30 transition hover:bg-white/10">
          <VideoOff aria-hidden size={15} />
        </button>
      </div>
    </section>
  );
}
