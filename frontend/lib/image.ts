/* Helpers for the picture inputs (camera frame / uploaded photo): downscale to a small JPEG so it is quick to send. */
const MAX_SIDE = 640;

export interface Photo {
  preview: string; // data URL, for the on-screen thumbnail only
  b64: string; // JPEG base64 without the data: prefix
}

function toPhoto(src: CanvasImageSource, w: number, h: number): Photo {
  const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * scale));
  c.height = Math.max(1, Math.round(h * scale));
  c.getContext("2d")!.drawImage(src, 0, 0, c.width, c.height);
  const preview = c.toDataURL("image/jpeg", 0.8);
  return { preview, b64: preview.split(",")[1] };
}

export function photoFromVideo(v: HTMLVideoElement): Photo | null {
  return v.videoWidth ? toPhoto(v, v.videoWidth, v.videoHeight) : null;
}

export async function photoFromFile(file: File): Promise<Photo> {
  if (!file.type.startsWith("image/")) throw new Error("Please choose an image file.");
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode().catch(() => { throw new Error("That image couldn't be opened. Try a JPEG or PNG."); });
    return toPhoto(img, img.naturalWidth, img.naturalHeight);
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function cameraErrorMessage(e: unknown): string {
  const n = (e as DOMException)?.name;
  return n === "NotAllowedError" || n === "SecurityError" ? "Camera access is blocked. Allow it from the lock icon in the address bar, or upload a photo instead."
    : n === "NotFoundError" || n === "OverconstrainedError" ? "No camera was found on this device. You can upload a photo instead."
    : n === "NotReadableError" || n === "AbortError" ? "The camera is in use by another app or tab. Close it and try again."
    : "The camera isn't available. You can upload a photo instead.";
}

export async function openCameraStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("unsupported"), { name: "NotFoundError" });
  try {
    return await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  } catch (e) {
    const n = (e as DOMException).name;
    if (n === "NotAllowedError" || n === "SecurityError") throw e;
    return navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  }
}
