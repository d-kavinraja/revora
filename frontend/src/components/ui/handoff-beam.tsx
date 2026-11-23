"use client";

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  BJORK_PALETTE,
  type BjorkTone,
} from "@/components/ui/handoff-beam-utils/palette";
import { useBjorkTone } from "@/components/ui/handoff-beam-utils/tone";
import { useVisibleLoop } from "@/components/ui/handoff-beam-utils/loop";
import { useElementSize } from "@/components/ui/handoff-beam-utils/canvas";
import {
  stepSpring,
  type SpringConfig,
  type SpringState,
} from "@/components/ui/handoff-beam-utils/spring";
import { valueNoise1D } from "@/components/ui/handoff-beam-utils/random";
import { LiveRegion } from "@/components/ui/handoff-beam-utils/a11y";

export type BeamPhase = "idle" | "listening" | "thinking" | "speaking";
export type BeamLevel = number | (() => number | [number, number, number]);

export interface HandoffBeamProps {
  phase: BeamPhase;
  level?: BeamLevel;
  analyser?: AnalyserNode | null;
  children?: ReactNode;
  /** Corner radius of the host, so the light is clipped to it. */
  radius?: number; // 32
  /** Height in px the light may rise into the host from its bottom edge. */
  reach?: number; // 22
  intensity?: number; // 1
  /** "ember", "mono", or up to five colours: centre, edge, thinking, listening edge, speaking edge. */
  palette?: "ember" | "mono" | string[]; // "ember"
  /** Horizontal centre of the light, 0 to 1. */
  gatherOffset?: number; // 0.5
  /** How far the thinking shimmer lifts the line, 0 to 1. */
  heldLevel?: number; // 0.45
  attack?: number; // 70 ms
  release?: number; // 260 ms
  threshold?: number; // 0.06
  sensitivity?: number; // 1.4
  phaseLabels?: Partial<Record<BeamPhase, string>>;
  tone?: BjorkTone;
  attract?: boolean;
  className?: string;
}

const DEFAULT_LABELS: Record<BeamPhase, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

const PHASE_INDEX: Record<BeamPhase, number> = {
  idle: 0,
  listening: 1,
  thinking: 2,
  speaking: 3,
};

const MORPH: SpringConfig = { stiffness: 64, damping: 16, mass: 1 };
const SPAN = [0.16, 0.6, 0.3, 0.5];
const BRIGHT = [0.42, 0.55, 0.85, 0.62];
const BRIGHT_GAIN = [0, 0.45, 0, 0.35];

const POINTS = 96;
const RAMP = 96;
const SHIMMER_S = 1.5;
const SHIMMER_W = 0.22;
const IDLE_BREATH_HZ = 0.2;
const LISTEN_FLOOR = 0.07;
const RESUME_IDLE_S = 4;
const DPR_CAP = 2;
const STATIC_CLOCK = 0.8;
const STATIC_RAW: [number, number, number] = [0.6, 0.45, 0.3];

const ATTRACT_SEGMENTS: Array<{ phase: BeamPhase; until: number }> = [
  { phase: "listening", until: 3 },
  { phase: "thinking", until: 5 },
  { phase: "speaking", until: 8 },
  { phase: "idle", until: 9.5 },
];
const ATTRACT_PERIOD = 9.5;

const subscribeNoop = () => () => {};
const getMounted = () => true;
const getServerMounted = () => false;

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function smoothstep01(u: number): number {
  const c = clamp01(u);
  return c * c * (3 - 2 * c);
}

function bump(p: number): number {
  return 0.5 + 0.5 * Math.cos(2 * Math.PI * p);
}

function hexToRgb(hex: string, out: Float32Array, at: number) {
  let h = hex.trim().replace("#", "");
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const n = parseInt(h.slice(0, 6), 16);
  const ok = Number.isFinite(n);
  out[at] = ok ? (n >> 16) & 255 : 236;
  out[at + 1] = ok ? (n >> 8) & 255 : 92;
  out[at + 2] = ok ? n & 255 : 19;
}

interface PaletteSpec {
  key: string;
  core: string[];
  edge: string[];
  glow: number;
  gain: number;
}

function resolvePalette(
  palette: HandoffBeamProps["palette"],
  tone: BjorkTone,
): PaletteSpec {
  const dark = tone === "dark";
  const tokens = BJORK_PALETTE[tone];
  if (Array.isArray(palette) && palette.length > 0) {
    const c = (i: number) =>
      palette[Math.min(i, palette.length - 1)] ?? tokens.accent;
    return {
      key: `custom:${tone}:${palette.join(",")}`,
      core: [c(0), c(0), c(2), c(0)],
      edge: [c(0), c(3), c(1), c(4)],
      glow: dark ? 1 : 0.6,
      gain: dark ? 1 : 1.7,
    };
  }
  if (palette === "mono") {
    const t = tokens.text;
    return {
      key: `mono:${tone}`,
      core: [t, t, t, t],
      edge: [t, t, t, t],
      glow: dark ? 0.8 : 0.45,
      gain: dark ? 1 : 1.2,
    };
  }
  if (dark) {
    return {
      key: "ember:dark",
      core: ["#ec5c13", "#ff7a2e", "#ffd1a1", "#ff8a3d"],
      edge: ["#ec5c13", "#ff5ea8", "#ff8a3d", "#ffb36b"],
      glow: 1,
      gain: 1,
    };
  }
  return {
    key: "ember:light",
    core: ["#dc4a0c", "#e0601c", "#ec7d2e", "#d4541a"],
    edge: ["#dc4a0c", "#d63c86", "#d4541a", "#e8862f"],
    glow: 0.85,
    gain: 1.7,
  };
}

interface Engine {
  w: [SpringState, SpringState, SpringState, SpringState];
  env: Float32Array;
  lvl: Float32Array;
  raw: [number, number, number];
  clock: number;
  now: number;
  inputAt: number;
  attractT: number;
  shimmerT: number;
  lastPhase: BeamPhase | null;
  ys: Float32Array;
  win: Float32Array;
  colors: Float32Array;
  colorKey: string;
  voiceListen: () => [number, number, number];
  voiceSpeak: () => [number, number, number];
  analyserNode: AnalyserNode | null;
  buf: Uint8Array<ArrayBuffer> | null;
  bins: Int32Array;
  ramp: HTMLCanvasElement | null;
  rampData: ImageData | null;
}

interface Latest {
  phase: BeamPhase;
  level: BeamLevel | undefined;
  analyser: AnalyserNode | null;
  attract: boolean;
  reduce: boolean;
  palette: PaletteSpec;
  intensity: number;
  center: number;
  heldLevel: number;
  attack: number;
  release: number;
  threshold: number;
  sensitivity: number;
  cssW: number;
  cssH: number;
}
function createEngine(phase: BeamPhase): Engine {
  const k = PHASE_INDEX[phase];
  const spring = (i: number): SpringState => ({ x: i === k ? 1 : 0, v: 0 });
  const win = new Float32Array(POINTS + 1);
  for (let i = 0; i <= POINTS; i++) {
    const u = (i / POINTS) * 2 - 1;
    const q = 1 - u * u;
    win[i] = q * q;
  }
  return {
    w: [spring(0), spring(1), spring(2), spring(3)],
    env: new Float32Array(3),
    lvl: new Float32Array(3),
    raw: [0, 0, 0],
    clock: 0,
    now: 0,
    inputAt: Number.NEGATIVE_INFINITY,
    attractT: 0,
    shimmerT: 0,
    lastPhase: null,
    ys: new Float32Array(POINTS + 1),
    win,
    colors: new Float32Array(24),
    colorKey: "",
    voiceListen: createSimulatedVoice(11),
    voiceSpeak: createSimulatedVoice(29),
    analyserNode: null,
    buf: null,
    bins: new Int32Array(6),
    ramp: null,
    rampData: null,
  };
}

function readLevel(e: Engine, level: BeamLevel | undefined) {
  const s =
    level === undefined ? 0 : typeof level === "function" ? level() : level;
  if (Array.isArray(s)) {
    e.raw[0] = s[0] ?? 0;
    e.raw[1] = s[1] ?? 0;
    e.raw[2] = s[2] ?? 0;
  } else {
    e.raw[0] = s;
    e.raw[1] = s * 0.8;
    e.raw[2] = s * 0.6;
  }
}

function readAnalyser(e: Engine, node: AnalyserNode) {
  if (e.analyserNode !== node) {
    e.analyserNode = node;
    e.buf = new Uint8Array(node.frequencyBinCount);
    const binHz = node.context.sampleRate / node.fftSize;
    const maxBin = node.frequencyBinCount - 1;
    const range = (lo: number, hi: number) => {
      const a = Math.min(maxBin, Math.max(1, Math.ceil(lo / binHz)));
      const b = Math.min(maxBin + 1, Math.max(a + 1, Math.floor(hi / binHz)));
      return [a, b];
    };
    const [l0, l1] = range(80, 300);
    const [m0, m1] = range(300, 2000);
    const [h0, h1] = range(2000, 6000);
    e.bins.set([l0, l1, m0, m1, h0, h1]);
  }
  const buf = e.buf;
  if (!buf) return;
  node.getByteFrequencyData(buf);
  for (let b = 0; b < 3; b++) {
    const lo = e.bins[b * 2];
    const hi = e.bins[b * 2 + 1];
    let sum = 0;
    for (let k = lo; k < hi; k++) sum += buf[k];
    e.raw[b] = hi > lo ? sum / (hi - lo) / 255 : 0;
  }
}

function ensureColors(e: Engine, spec: PaletteSpec) {
  if (e.colorKey === spec.key) return;
  for (let k = 0; k < 4; k++) {
    hexToRgb(spec.core[k], e.colors, k * 3);
    hexToRgb(spec.edge[k], e.colors, 12 + k * 3);
  }
  e.colorKey = spec.key;
  if (!e.ramp) {
    e.ramp = document.createElement("canvas");
    e.ramp.width = RAMP;
    e.ramp.height = 1;
    const rctx = e.ramp.getContext("2d");
    e.rampData = rctx ? rctx.createImageData(RAMP, 1) : null;
  }
}

function thickness(e: Engine, i: number, shimmerAt: number): number {
  if (Number.isNaN(shimmerAt)) return 0.25 + 0.75 * Math.sqrt(e.win[i]);
  const u = (i / POINTS) * 2 - 1;
  const d = (u - shimmerAt) / SHIMMER_W;
  return Math.exp(-d * d) * e.win[i];
}

function ribbon(
  ctx: CanvasRenderingContext2D,
  e: Engine,
  x0: number,
  dx: number,
  base: number,
  half: number,
  shimmerAt: number,
) {
  ctx.beginPath();
  for (let i = 0; i <= POINTS; i++) {
    const y = base - e.ys[i] - half * thickness(e, i, shimmerAt);
    if (i === 0) ctx.moveTo(x0, y);
    else ctx.lineTo(x0 + i * dx, y);
  }
  for (let i = POINTS; i >= 0; i--) {
    ctx.lineTo(x0 + i * dx, base - e.ys[i] + half * thickness(e, i, shimmerAt));
  }
  ctx.closePath();
  ctx.fill();
}
export function HandoffBeam({
  phase,
  level,
  analyser = null,
  children,
  radius = 32,
  reach = 22,
  intensity = 1,
  palette = "ember",
  gatherOffset = 0.5,
  heldLevel = 0.45,
  attack = 70,
  release = 260,
  threshold = 0.06,
  sensitivity = 1.4,
  phaseLabels,
  tone,
  attract = false,
  className,
}: HandoffBeamProps) {
  const resolvedTone = useBjorkTone(tone);
  const reducedPref = useReducedMotion();
  const mounted = useSyncExternalStore(
    subscribeNoop,
    getMounted,
    getServerMounted,
  );
  const reduce = mounted && reducedPref === true;

  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const size = useElementSize(rootRef);
  const engineRef = useRef<Engine | null>(null);

  const reachEff = size.height > 0 ? Math.min(reach, size.height) : reach;
  const paletteSpec = resolvePalette(palette, resolvedTone);
  const labels = { ...DEFAULT_LABELS, ...phaseLabels };

  const getEngine = (): Engine => {
    if (!engineRef.current)
      engineRef.current = createEngine(latest.current?.phase ?? phase);
    return engineRef.current;
  };

  const latest = useRef<Latest | null>(null);
  useEffect(() => {
    latest.current = {
      phase,
      level,
      analyser,
      attract,
      reduce,
      palette: paletteSpec,
      intensity,
      center: gatherOffset,
      heldLevel,
      attack,
      release,
      threshold,
      sensitivity,
      cssW: size.width,
      cssH: reachEff,
    };
  });

  const frame = (dtIn: number) => {
    const L = latest.current;
    const canvas = canvasRef.current;
    if (!L || !canvas) return;
    const e = getEngine();
    const dt = L.reduce ? 0 : dtIn;
    e.clock += dt;
    e.now += dtIn;
    const t = L.reduce ? STATIC_CLOCK : e.clock;

    const cssW = L.cssW;
    const cssH = L.cssH;
    if (cssW <= 0 || cssH <= 0) return;

    const inputActive = e.now >= e.inputAt && e.now - e.inputAt < RESUME_IDLE_S;
    let phaseNow: BeamPhase = L.phase;
    let levelSource: BeamLevel | undefined = L.level;
    let analyserNode: AnalyserNode | null = L.analyser;
    if (L.attract && !inputActive) {
      if (L.reduce) {
        phaseNow = "listening";
      } else {
        e.attractT = (e.attractT + dt) % ATTRACT_PERIOD;
        let seg = ATTRACT_SEGMENTS[0];
        for (let k = 0; k < ATTRACT_SEGMENTS.length; k++) {
          if (e.attractT < ATTRACT_SEGMENTS[k].until) {
            seg = ATTRACT_SEGMENTS[k];
            break;
          }
        }
        phaseNow = seg.phase;
        levelSource = seg.phase === "speaking" ? e.voiceSpeak : e.voiceListen;
      }
      analyserNode = null;
    }
    if (phaseNow === "thinking" && e.lastPhase !== "thinking") e.shimmerT = 0;
    e.lastPhase = phaseNow;

    const target = PHASE_INDEX[phaseNow];
    for (let k = 0; k < 4; k++) {
      const s = e.w[k];
      if (L.reduce) {
        s.x = k === target ? 1 : 0;
        s.v = 0;
      } else {
        stepSpring(s, k === target ? 1 : 0, MORPH, dt);
      }
    }
    const wI = clamp01(e.w[0].x);
    const wL = clamp01(e.w[1].x);
    const wT = clamp01(e.w[2].x);
    const wS = clamp01(e.w[3].x);

    if (L.reduce && !analyserNode) {
      e.raw[0] = STATIC_RAW[0];
      e.raw[1] = STATIC_RAW[1];
      e.raw[2] = STATIC_RAW[2];
    } else if (analyserNode) {
      readAnalyser(e, analyserNode);
    } else {
      readLevel(e, levelSource);
    }
    const smoothTau = 0.07 + 0.2 * wS;
    for (let b = 0; b < 3; b++) {
      const r = e.raw[b] < L.threshold ? 0 : clamp01(e.raw[b] * L.sensitivity);
      if (L.reduce) {
        e.env[b] = r;
        e.lvl[b] = r;
      } else {
        const tau = Math.max(1, r > e.env[b] ? L.attack : L.release) / 1000;
        e.env[b] += (r - e.env[b]) * (1 - Math.exp(-dtIn / tau));
        e.lvl[b] += (e.env[b] - e.lvl[b]) * (1 - Math.exp(-dtIn / smoothTau));
      }
    }
    const low = e.lvl[0];
    const mid = e.lvl[1];
    const high = e.lvl[2];
    const energy = clamp01(low * 0.5 + mid * 0.3 + high * 0.2);

    if (!L.reduce) e.shimmerT += dt * (0.35 + 0.65 * wT);
    const shimmerAt = L.reduce
      ? 0
      : -1.4 + 2.8 * ((e.shimmerT / SHIMMER_S) % 1);
    const breath = L.reduce ? 0 : Math.sin(2 * Math.PI * IDLE_BREATH_HZ * t);

    const span = wI * SPAN[0] + wL * SPAN[1] + wT * SPAN[2] + wS * SPAN[3];
    const bright =
      wI * (BRIGHT[0] + 0.1 * breath) +
      wL * (BRIGHT[1] + BRIGHT_GAIN[1] * energy) +
      wT * BRIGHT[2] +
      wS * (BRIGHT[3] + BRIGHT_GAIN[3] * energy);
    const amp = cssH * 0.7;
    const speakAmp = 0.28 + 0.72 * energy;
    const held = clamp01(L.heldLevel);

    for (let i = 0; i <= POINTS; i++) {
      const u = (i / POINTS) * 2 - 1;
      const d = Math.sqrt(u * u + 0.004);
      const listen =
        LISTEN_FLOOR * bump(1.1 * d + 0.55 * t) +
        low * 0.75 * bump(1.1 * d + 0.55 * t) +
        mid * 0.4 * bump(2.3 * d + 0.95 * t + 0.18 * u) +
        high * 0.24 * bump(3.8 * d + 1.5 * t - 0.3 * u);
      const speak =
        speakAmp *
        (0.22 +
          0.5 * bump(1.25 * d - 0.62 * t) +
          0.12 * bump(2.6 * d - 1.24 * t));
      const sd = (u - shimmerAt) / (SHIMMER_W * 1.6);
      const think = held * (0.12 + 0.4 * Math.exp(-sd * sd));
      e.ys[i] = amp * e.win[i] * (wL * listen + wS * speak + wT * think);
    }

    ensureColors(e, L.palette);
    const ramp = e.ramp;
    const data = e.rampData;
    if (!ramp || !data) return;
    const C = e.colors;
    let cr = 0,
      cg = 0,
      cb = 0,
      er = 0,
      eg = 0,
      eb = 0;
    for (let k = 0; k < 4; k++) {
      const wk = clamp01(e.w[k].x);
      cr += wk * C[k * 3];
      cg += wk * C[k * 3 + 1];
      cb += wk * C[k * 3 + 2];
      er += wk * C[12 + k * 3];
      eg += wk * C[12 + k * 3 + 1];
      eb += wk * C[12 + k * 3 + 2];
    }
    const px = data.data;
    for (let j = 0; j < RAMP; j++) {
      const u = ((j + 0.5) / RAMP) * 2 - 1;
      const d = u < 0 ? -u : u;
      const m = smoothstep01((d - 0.15) / 0.75);
      const sd = (u - shimmerAt) / SHIMMER_W;
      const lift = wT * Math.exp(-sd * sd);
      const q = 1 - d * d;
      const a = clamp01(
        bright *
          L.palette.gain *
          L.intensity *
          q *
          Math.sqrt(q) *
          (1 + 0.55 * lift),
      );
      const o = j * 4;
      px[o] = cr + (er - cr) * m;
      px[o + 1] = cg + (eg - cg) * m;
      px[o + 2] = cb + (eb - cb) * m;
      px[o + 3] = a * 255;
    }
    const rctx = ramp.getContext("2d");
    if (!rctx) return;
    rctx.putImageData(data, 0, 0);
    const dpr = Math.min(
      typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1,
      DPR_CAP,
    );
    const bw = Math.max(1, Math.round(cssW * dpr));
    const bh = Math.max(1, Math.round(cssH * dpr));
    if (canvas.width !== bw) canvas.width = bw;
    if (canvas.height !== bh) canvas.height = bh;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(bw / cssW, 0, 0, bh / cssH, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, cssW, cssH);

    const spanPx = Math.max(8, span * cssW);
    const x0 = Math.min(
      cssW - spanPx,
      Math.max(0, L.center * cssW - spanPx / 2),
    );
    const dx = spanPx / POINTS;
    const base = cssH - 1;
    const glow = L.palette.glow;

    ctx.fillStyle = "#fff";
    for (let layer = 1; layer <= 3; layer++) {
      const f = layer / 3;
      ctx.globalAlpha = 0.045 * glow;
      ctx.beginPath();
      ctx.moveTo(x0, base);
      for (let i = 0; i <= POINTS; i++)
        ctx.lineTo(x0 + i * dx, base - e.ys[i] * f);
      ctx.lineTo(x0 + spanPx, base);
      ctx.closePath();
      ctx.fill();
    }
    ctx.globalAlpha = 0.07 * glow;
    ribbon(ctx, e, x0, dx, base, 5.5, Number.NaN);
    ctx.globalAlpha = 0.26 * glow;
    ribbon(ctx, e, x0, dx, base, 2.2, Number.NaN);
    ctx.globalAlpha = 1;
    ribbon(ctx, e, x0, dx, base, 0.85, Number.NaN);
    if (wT > 0.01) {
      ctx.globalAlpha = 0.5 * wT;
      ribbon(ctx, e, x0, dx, base, 1.6, shimmerAt);
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-in";
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(ramp, x0, 0, spanPx, cssH);
    ctx.globalCompositeOperation = "source-over";
  };

  useVisibleLoop(rootRef, frame, {
    fpsCap: reduce ? 10 : 0,
  });

  const noteInput = () => {
    const e = getEngine();
    e.inputAt = e.now;
  };

  return (
    <div
      ref={rootRef}
      data-phase={phase}
      onPointerDown={noteInput}
      onPointerMove={noteInput}
      onKeyDown={noteInput}
      className={cn("relative w-full overflow-hidden", className)}
      style={{ borderRadius: radius }}
    >
      {children}
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 block"
        style={{ width: "100%", height: reachEff }}
      />
      <LiveRegion message={labels[phase]} />
    </div>
  );
}

export function createSimulatedVoice(
  seed: number,
): () => [number, number, number] {
  const phrase = valueNoise1D(seed);
  const pitch = valueNoise1D(seed + 53);
  const out: [number, number, number] = [0, 0, 0];
  let t0 = -1;
  return () => {
    const now = typeof performance !== "undefined" ? performance.now() : 0;
    if (t0 < 0) t0 = now;
    const x = (now - t0) / 1000;
    const carrier =
      0.5 + 0.5 * Math.sin(2 * Math.PI * 3.1 * x + 1.7 * pitch(x * 0.6));
    const speaking = clamp01(phrase(x * 0.7) * 2);
    const env = clamp01(carrier * carrier * speaking);
    out[0] = clamp01(env * (0.9 + 0.1 * pitch(x * 1.9)));
    out[1] = clamp01(env * (0.7 + 0.2 * pitch(x * 2.6)));
    out[2] = clamp01(env * (0.45 + 0.2 * pitch(x * 3.4)));
    return out;
  };
}

export default HandoffBeam;
