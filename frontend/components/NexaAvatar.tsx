"use client";
import { useEffect, useRef, useState } from "react";
import type { BufferGeometry, Material, Mesh, Object3D } from "three";
import type { Emotion } from "@/lib/emotion";
import { subscribeSpeech } from "@/lib/speech";

/* NEXA's character: a procedural 3D koala (three.js, no external assets), modelled on the koala sheets we were given:
   grey fur, big fluffy pink-and-cream ears, large dark nose, brown eyes, rosy cheeks. The head follows the cursor, it
   blinks, floats and squashes when poked. Its face shows an emotion chosen from what the person said, and when NEXA
   talks aloud the mouth lip-syncs to the spoken text. Decorative: if WebGL fails, nothing is rendered. */
const AURA: Record<string, string> = {
  idle: "rgb(185 168 230 / 0.55)", listening: "rgb(181 222 201 / 0.85)", speaking: "rgb(150 120 255 / 0.65)",
  understanding: "rgb(183 221 242 / 0.7)", matching: "rgb(245 237 206 / 0.9)", emergency: "rgb(244 183 168 / 0.9)",
};

/* face targets per emotion; the model eases toward these each frame.
   smile: +curve smile / -curve frown, brow: inner-end raise (worry), browY: lift, eye: lid openness (<1 squints),
   open: mouth, blush: cheek opacity, ear: +perk / -droop, tilt: head roll */
type Face = { smile: number; brow: number; browY: number; eye: number; open: number; blush: number; ear: number; tilt: number };
const FACE: Record<Emotion, Face> = {
  neutral: { smile: 1, brow: 0.25, browY: 0, eye: 1, open: 0, blush: 0.75, ear: 0, tilt: 0 },
  happy: { smile: 2, brow: 0.05, browY: 0.06, eye: 0.55, open: 0.18, blush: 1, ear: 0.12, tilt: 0.05 },
  love: { smile: 1.7, brow: 0.1, browY: 0.05, eye: 0.5, open: 0.05, blush: 1, ear: 0.1, tilt: -0.08 },
  worried: { smile: -0.6, brow: 0.6, browY: 0.1, eye: 1.15, open: 0, blush: 0.35, ear: -0.3, tilt: 0.08 },
  sad: { smile: -1.3, brow: 0.65, browY: 0, eye: 0.75, open: 0, blush: 0.5, ear: -0.4, tilt: -0.1 },
  surprised: { smile: 0, brow: 0, browY: 0.18, eye: 1.3, open: 0.85, blush: 0.75, ear: 0.25, tilt: 0 },
  thinking: { smile: 0.2, brow: -0.12, browY: 0.04, eye: 0.9, open: 0, blush: 0.75, ear: 0.05, tilt: 0.14 },
};

/* letter -> mouth shape: open (jaw) and wide (lip spread). Vowels carry the shape; m/b/p close the lips. */
function viseme(ch: string): { open: number; wide: number } {
  const c = ch.toLowerCase();
  if ("a".includes(c)) return { open: 0.95, wide: 1.05 };
  if ("e".includes(c)) return { open: 0.6, wide: 1.3 };
  if ("i".includes(c) || c === "y") return { open: 0.38, wide: 1.4 };
  if ("o".includes(c)) return { open: 0.75, wide: 0.7 };
  if ("u".includes(c) || c === "w") return { open: 0.45, wide: 0.55 };
  if ("mbp".includes(c)) return { open: 0.02, wide: 1 };
  if ("fv".includes(c)) return { open: 0.14, wide: 1.05 };
  if (/[a-z]/.test(c)) return { open: 0.3, wide: 1.05 };
  if (/[.,!?;:]/.test(c)) return { open: 0, wide: 1 };
  return { open: 0.08, wide: 1 };
}

export function NexaAvatar({ className, mode = "idle", emotion = "neutral" }: { className?: string; mode?: string; emotion?: Emotion }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef(mode);
  const emoRef = useRef<Emotion>(emotion);
  const pokeRef = useRef(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => { modeRef.current = mode; emoRef.current = emotion; }, [mode, emotion]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let cleanup = () => {};
    (async () => {
      try {
        const THREE = await import("three");
        if (disposed) return;
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setClearColor(0x000000, 0);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
        camera.position.set(0, 0.2, 10);
        scene.add(new THREE.HemisphereLight(0xffffff, 0xb9a8e6, 1.5));
        const key = new THREE.DirectionalLight(0xfff4e6, 2.4); key.position.set(3, 5, 6); scene.add(key);
        const rim = new THREE.DirectionalLight(0xbfa8ff, 1.2); rim.position.set(-4, 2, -3); scene.add(rim);

        const mat = (color: number, rough = 0.85) => new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0 });
        const fur = mat(0x8f9cbc), furLight = mat(0xa4b0cc), cream = mat(0xf6e8d3), pink = mat(0xf2a9a2, 0.7);
        const nose = new THREE.MeshPhysicalMaterial({ color: 0x23222e, roughness: 0.3, clearcoat: 0.8 });
        const eyeM = new THREE.MeshPhysicalMaterial({ color: 0x4a2a1a, roughness: 0.15, clearcoat: 1 });
        const shine = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const dark = mat(0x2a1f2a, 0.6), mouthM = mat(0xd9605e, 0.6), cheek = mat(0xf5a6a0, 0.9);
        cheek.transparent = true; cheek.opacity = 0.75;
        const smileM = new THREE.MeshStandardMaterial({ color: 0x2a1f2a, roughness: 0.6, side: THREE.DoubleSide });
        const mats: Material[] = [fur, furLight, cream, pink, nose, eyeM, shine, dark, mouthM, cheek, smileM];
        const geos: BufferGeometry[] = [];
        const ball = (r: number, m: Material, parent: Object3D, x = 0, y = 0, z = 0, sx = 1, sy = 1, sz = 1) => {
          const g = new THREE.SphereGeometry(r, 48, 36); geos.push(g);
          const mesh = new THREE.Mesh(g, m); mesh.position.set(x, y, z); mesh.scale.set(sx, sy, sz); parent.add(mesh); return mesh;
        };

        const root = new THREE.Group(); scene.add(root);
        const squash = new THREE.Group(); root.add(squash);
        // body, belly, arms
        ball(1.35, fur, squash, 0, -1.9, 0, 1, 0.85, 0.8);
        ball(0.95, cream, squash, 0, -1.85, 0.55, 1, 0.9, 0.5);
        for (const sx of [-1, 1]) { ball(0.45, fur, squash, sx * 1.15, -1.55, 0.3, 1, 1.3, 1); ball(0.3, furLight, squash, sx * 1.2, -2.0, 0.45); }

        // head
        const head = new THREE.Group(); head.position.set(0, 0.15, 0); squash.add(head);
        ball(1.3, fur, head, 0, 0, 0, 1.12, 0.98, 1);
        ball(0.5, furLight, head, 0, 1.05, 0.1, 1.3, 0.6, 0.9); // fur tuft
        for (const sx of [-0.35, 0.35]) ball(0.22, furLight, head, sx, 1.22, 0.1, 0.8, 1.2, 0.8);
        // ears: fluffy cream rim, pink inner
        const ears: Object3D[] = [];
        for (const sx of [-1, 1]) {
          const ear = new THREE.Group(); ear.position.set(sx * 1.45, 0.75, -0.05); head.add(ear);
          ball(0.78, fur, ear, 0, 0, 0, 1, 1, 0.55);
          ball(0.66, cream, ear, 0, -0.02, 0.17, 1, 1, 0.5);
          ball(0.5, pink, ear, 0, -0.03, 0.26, 1, 1, 0.45);
          ears.push(ear);
        }
        // muzzle + big nose
        ball(0.82, cream, head, 0, -0.45, 0.78, 1.15, 0.85, 0.7);
        const noseM: Mesh = ball(0.4, nose, head, 0, -0.02, 1.32, 1.1, 0.85, 0.75);
        ball(0.09, shine, head, -0.1, 0.1, 1.62, 1, 0.7, 0.5);
        // eyes (brown, with highlights); the group scales down to blink; brows and cheeks carry the emotion
        const eyes: Object3D[] = [];
        const brows: { mesh: Mesh; side: number; y: number }[] = [];
        for (const sx of [-0.62, 0.62]) {
          const e = new THREE.Group(); e.position.set(sx, 0.22, 1.12); head.add(e);
          ball(0.25, eyeM, e, 0, 0, 0, 0.95, 1.1, 0.55);
          ball(0.08, shine, e, 0.07, 0.1, 0.15);
          ball(0.04, shine, e, -0.07, -0.08, 0.15);
          const brow = ball(0.12, dark, head, sx * 1.05, 0.62, 1.05, 1.4, 0.3, 0.5);
          brows.push({ mesh: brow, side: Math.sign(sx), y: 0.62 });
          ball(0.22, cheek, head, sx * 1.02, -0.3, 1.0, 1, 0.7, 0.3);
          eyes.push(e);
        }
        // mouth: a smile arc (scaled negative = frown) and an open-mouth shape used for talking
        const smileG = new THREE.TorusGeometry(0.2, 0.025, 8, 24, Math.PI); geos.push(smileG);
        const smile = new THREE.Mesh(smileG, smileM); smile.rotation.z = Math.PI; smile.position.set(0, -0.62, 1.34); head.add(smile);
        const mouth = ball(0.15, mouthM, head, 0, -0.72, 1.3, 1.1, 0.01, 0.4);

        // expression props: heart (love), tear (sad), sweat drop (worried), sparkles (happy / surprised)
        const heartS = new THREE.Shape();
        heartS.moveTo(0, -0.3); heartS.bezierCurveTo(-0.5, 0.05, -0.3, 0.45, 0, 0.2); heartS.bezierCurveTo(0.3, 0.45, 0.5, 0.05, 0, -0.3);
        const heartG = new THREE.ExtrudeGeometry(heartS, { depth: 0.12, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03 }); geos.push(heartG);
        const heartM = new THREE.MeshStandardMaterial({ color: 0xff6b81, roughness: 0.4, emissive: 0xff3b5c, emissiveIntensity: 0.35 });
        const heart = new THREE.Mesh(heartG, heartM); heart.position.set(0, 2.45, 0.4); heart.scale.setScalar(0); head.add(heart);
        const dropM = new THREE.MeshStandardMaterial({ color: 0x8fd3ff, roughness: 0.15, transparent: true, opacity: 0.9 });
        const sweat = ball(0.14, dropM, head, 1.0, 0.85, 1.05, 0.8, 1.3, 0.6); sweat.scale.setScalar(0);
        const tears = [-0.62, 0.62].map((x) => { const t = ball(0.1, dropM, head, x, -0.15, 1.28, 0.8, 1.3, 0.6); t.scale.setScalar(0); return t; });
        const starM = new THREE.MeshStandardMaterial({ color: 0xffe27a, emissive: 0xffc83d, emissiveIntensity: 0.8 });
        const starG = new THREE.OctahedronGeometry(0.16); geos.push(starG);
        const starY = [1.9, 2.5, 1.9];
        const stars = [[-1.4, 1.9], [0, 2.5], [1.4, 1.9]].map(([x, y]) => { const s = new THREE.Mesh(starG, starM); s.position.set(x, y, 0.4); s.scale.setScalar(0); head.add(s); return s; });
        mats.push(heartM, dropM, starM);

        // contact shadow
        const shadowM = new THREE.MeshBasicMaterial({ color: 0x4a3f7a, transparent: true, opacity: 0.18 });
        const sh = new THREE.Mesh(new THREE.CircleGeometry(1.6, 48), shadowM);
        sh.rotation.x = -Math.PI / 2; sh.position.y = -3.55; scene.add(sh); geos.push(sh.geometry); mats.push(shadowM);

        // lip sync: follow the spoken text (see subscribeSpeech in lib/speech.ts)
        const lip = { active: false, text: "", pos: 0, cps: 14, at: 0 };
        const unsub = subscribeSpeech((e) => {
          if (e.type === "start") { lip.active = true; lip.text = e.text; lip.pos = 0; lip.cps = 15 * e.rate; lip.at = performance.now(); }
          else if (e.type === "boundary") { lip.pos = e.charIndex; lip.at = performance.now(); }
          else lip.active = false;
        });

        const look = { x: 0, y: 0 };
        const onMove = (e: MouseEvent) => { look.x = (e.clientX / window.innerWidth) * 2 - 1; look.y = (e.clientY / window.innerHeight) * 2 - 1; };
        window.addEventListener("mousemove", onMove);
        const onDown = (e: PointerEvent) => {
          const r = canvas.getBoundingClientRect();
          if (Math.hypot((e.clientX - (r.left + r.width / 2)) / r.width, (e.clientY - (r.top + r.height * 0.45)) / r.height) < 0.3) pokeRef.current = performance.now();
        };
        window.addEventListener("pointerdown", onDown);

        const resize = () => {
          const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
          renderer.setSize(w, h, false);
          camera.aspect = w / h;
          camera.position.z = w / h < 0.9 ? 14 : 10.5;
          camera.updateProjectionMatrix();
        };
        const ro = new ResizeObserver(resize); ro.observe(canvas); resize();

        const f: Face = { ...FACE.neutral };
        const ease = (a: number, b: number, k = 0.1) => a + (b - a) * k;
        const show = (o: Object3D, on: boolean) => o.scale.setScalar(ease(o.scale.x, on ? 1 : 0, 0.12));
        let mouthOpen = 0, mouthWide = 1;
        const clock = new THREE.Clock();
        let raf = 0, nextBlink = 2;
        const frame = () => {
          raf = requestAnimationFrame(frame);
          const t = clock.getElapsedTime(), m = modeRef.current, em = emoRef.current, k = reduced ? 0 : 1;
          root.position.y = Math.sin(t * 1.4) * 0.08 * k;
          head.rotation.y += (look.x * 0.55 - head.rotation.y) * 0.08;
          head.rotation.x += (look.y * 0.3 - head.rotation.x) * 0.08;
          squash.rotation.y += (look.x * 0.15 - squash.rotation.y) * 0.05;
          // poke: squash and bounce
          const pt = (performance.now() - pokeRef.current) / 420;
          if (pt >= 0 && pt < 1 && k) { const s = Math.sin(pt * Math.PI * 2.5) * (1 - pt) * 0.14; squash.scale.set(1 + s, 1 - s, 1 + s); }
          else squash.scale.set(1, 1, 1);

          // ease the face toward the current emotion
          const T = FACE[em] ?? FACE.neutral;
          (Object.keys(f) as (keyof Face)[]).forEach((key) => { f[key] = ease(f[key], T[key], reduced ? 1 : 0.1); });
          head.rotation.z += (Math.sin(t * 0.9) * 0.03 * k + f.tilt - head.rotation.z) * 0.1;
          brows.forEach((b) => { b.mesh.rotation.z = -b.side * f.brow; b.mesh.position.y = b.y + f.browY; });
          cheek.opacity = f.blush;
          // blink (f.eye < 1 squints for happy / sad)
          if (t > nextBlink) { eyes.forEach((e) => (e.scale.y = 0.08)); if (t > nextBlink + 0.13) nextBlink = t + 2 + Math.random() * 3; }
          else eyes.forEach((e) => (e.scale.y += (f.eye - e.scale.y) * 0.45));
          // ears perk when listening or happy, droop when worried or sad, flick gently otherwise
          ears.forEach((e, i) => { const tgt = ((m === "listening" ? 0.22 : 0) + f.ear) * (i ? -1 : 1) + Math.sin(t * 1.1 + i) * 0.03 * k; e.rotation.z += (tgt - e.rotation.z) * 0.1; });

          // mouth: lip sync while speaking aloud; otherwise the emotion's own shape
          let tOpen = f.open, tWide = 1;
          if (lip.active && lip.text) {
            const pos = Math.min(lip.text.length - 1, lip.pos + ((performance.now() - lip.at) / 1000) * lip.cps);
            const v = viseme(lip.text[Math.max(0, Math.floor(pos))] ?? " ");
            tOpen = Math.max(f.open * 0.5, v.open); tWide = v.wide;
          } else if (m === "speaking") {
            tOpen = Math.max(f.open, reduced ? 0.6 : 0.35 + (Math.sin(t * 13) + 1) * 0.45); // voice off: simple flap
          } else if (m === "listening") tOpen = Math.max(f.open, 0.3);
          mouthOpen = ease(mouthOpen, tOpen, lip.active ? 0.5 : 0.3);
          mouthWide = ease(mouthWide, tWide, 0.45);
          mouth.scale.set(1.1 * mouthWide, Math.max(0.01, mouthOpen), 0.4);
          smile.visible = mouthOpen < 0.2;
          smile.scale.y = f.smile; // negative flips the arc into a frown
          smile.position.y = -0.62 - (f.smile < 0 ? 0.1 : 0);
          noseM.scale.y = 0.85 + Math.sin(t * 2) * 0.02 * k;

          // props
          show(heart, em === "love");
          heart.position.y = 2.45 + Math.sin(t * 2.4) * 0.08 * k; heart.rotation.y = Math.sin(t * 1.5) * 0.4 * k;
          show(sweat, em === "worried");
          sweat.position.y = 0.85 - ((t * 0.5) % 1) * 0.1 * k;
          tears.forEach((tr) => { show(tr, em === "sad"); tr.position.y = -0.15 - ((t * 0.6) % 1) * 0.55 * k; });
          stars.forEach((st, i) => { show(st, em === "happy" || em === "surprised"); st.rotation.y = t * 1.5 * k + i; st.position.y = starY[i] + Math.sin(t * 3 + i) * 0.06 * k; });
          renderer.render(scene, camera);
        };
        frame();

        cleanup = () => {
          cancelAnimationFrame(raf);
          unsub();
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("pointerdown", onDown);
          ro.disconnect();
          geos.forEach((g) => g.dispose());
          mats.forEach((x) => x.dispose());
          renderer.dispose();
        };
        if (disposed) cleanup();
      } catch {
        if (!disposed) setFailed(true);
      }
    })();
    return () => { disposed = true; cleanup(); };
  }, []);

  if (failed) return null;
  const aura = AURA[mode] ?? AURA.idle;
  return (
    <div className={className} style={{ position: "relative" }}>
      <div aria-hidden style={{ position: "absolute", left: "50%", top: "46%", width: "min(70vh, 80vw)", height: "min(70vh, 80vw)", transform: "translate(-50%, -50%)", borderRadius: "50%", background: `radial-gradient(circle, ${aura} 0%, transparent 68%)`, transition: "background 0.4s" }} />
      <canvas ref={canvasRef} aria-hidden="true" className="absolute inset-0 h-full w-full" />
    </div>
  );
}
