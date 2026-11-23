"use client";

import { useEffect, useRef, useState } from "react";

export interface ThinkingOrbProps {
  /** True while the backend is preparing/thinking. False triggers the emerald Done sweep. */
  active?: boolean;
  /** Sphere diameter in CSS pixels. */
  size?: number;
  className?: string;
}

/**
 * Deterministic Fibonacci-sphere point cloud. Stored once at module load so the
 * sphere shape never changes between renders (no random jitter or flicker).
 */
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const DOT_COUNT = 640;
type Dot = { x: number; y: number; z: number; seed: number };
const DOT_LIST: Dot[] = Array.from({ length: DOT_COUNT }, (_, i) => {
  const y = 1 - (i / (DOT_COUNT - 1)) * 2;
  const ring = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = GOLDEN_ANGLE * i;
  return {
    x: Math.cos(theta) * ring,
    y,
    z: Math.sin(theta) * ring,
    seed: (i * 0.6180339887498949) % 1,
  };
});

const STAGES = ["Thinking…", "Searching…", "Analyzing…", "Composing…"] as const;

/** Theme-aware particle colours: silver-white → emerald (dark), slate → emerald (light). */
function palette(dark: boolean) {
  return dark
    ? { base: [235, 235, 235] as const, accent: [52, 211, 153] as const, glow: "52, 211, 153" }
    : { base: [30, 41, 59] as const, accent: [16, 185, 129] as const, glow: "16, 185, 129" };
}

function useDarkMode() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const read = () => {
      const list = document.documentElement.classList;
      setDark(list.contains("dark") || list.contains("admin-dark"));
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

/**
 * Self-contained 3D dotted thinking orb. No input, no inline SVG, no external
 * styles required: it renders only the particle sphere and its status pill.
 */
export function ThinkingOrb({ active = true, size = 132, className = "" }: ThinkingOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const startRef = useRef(0);
  const exitAtRef = useRef<number | null>(null);
  const doneRef = useRef(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const dark = useDarkMode();
  const [label, setLabel] = useState<string>(STAGES[0]);
  const displayLabel = active ? label : "Done";

  // Stage cycling. The Done label is derived from `active` at render time.
  useEffect(() => {
    if (!active) return;
    let index = 0;
    queueMicrotask(() => setLabel(STAGES[index]));
    const id = window.setInterval(() => {
      index = (index + 1) % STAGES.length;
      setLabel(STAGES[index]);
    }, 1900);
    return () => window.clearInterval(id);
  }, [active]);

  // Lifecycle: (re)assembly on activation, emerald sweep + condense on deactivation.
  useEffect(() => {
    if (active) {
      exitAtRef.current = null;
      doneRef.current = false;
      startRef.current = performance.now();
      if (rootRef.current) rootRef.current.style.display = "";
    } else if (exitAtRef.current === null) {
      exitAtRef.current = performance.now();
    }
  }, [active]);

  // Render loop. Restart only when the theme or size changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const colors = palette(dark);
    const center = size / 2;
    let frame = 0;

    const draw = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const assemble = 1 - Math.pow(1 - Math.min(1, (now - startRef.current) / 780), 3);
      const exit = exitAtRef.current === null ? 0 : Math.min(1, (now - exitAtRef.current) / 900);
      const condense = 1 - exit * 0.26;
      const radius = size * 0.31 * assemble * condense;
      const alphaFade = 1 - exit;

      ctx.clearRect(0, 0, size, size);

      // Soft ambient glow behind the sphere.
      const glow = ctx.createRadialGradient(center, center, 0, center, center, size * 0.48);
      glow.addColorStop(0, `rgba(${colors.glow},${dark ? 0.11 : 0.08})`);
      glow.addColorStop(1, `rgba(${colors.glow},0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);

      const ay = now * 0.00028;
      const ax = Math.sin(now * 0.00017) * 0.32 + 0.12;
      const cosY = Math.cos(ay);
      const sinY = Math.sin(ay);
      const cosX = Math.cos(ax);
      const sinX = Math.sin(ax);

      for (const dot of DOT_LIST) {
        const rx = dot.x * cosY - dot.z * sinY;
        const rz0 = dot.x * sinY + dot.z * cosY;
        const ry = dot.y * cosX - rz0 * sinX;
        const rz = dot.y * sinX + rz0 * cosX;

        const perspective = 1 / (2.6 - rz);
        const scale = perspective * 2.2;
        const px = center + rx * radius * scale;
        const py = center + ry * radius * scale;
        if (px < -4 || px > size + 4 || py < -4 || py > size + 4) continue;

        const depth = (rz + 1) / 2;
        // Three independent light programs travelling over the sphere.
        const pulseA = 0.5 + 0.5 * Math.sin(now * 0.0021 + dot.seed * Math.PI * 2);
        const pulseB = 0.5 + 0.5 * Math.sin(now * 0.0009 - dot.x * 4 + dot.y * 3);
        const pulseC = 0.5 + 0.5 * Math.sin(now * 0.0015 + dot.z * 5);
        const shimmer = 0.55 + 0.45 * (pulseA * pulseB * 0.6 + pulseC * 0.4);
        // Emerald sweeps across the sphere on completion.
        const sweep = exit > 0 ? Math.max(0, 1 - Math.abs(rz - (exit * 2 - 1)) / 0.35) : 0;
        const emerald = Math.max(sweep, Math.pow(shimmer, 3) * 0.35);

        const r = Math.round(colors.base[0] + (colors.accent[0] - colors.base[0]) * emerald);
        const g = Math.round(colors.base[1] + (colors.accent[1] - colors.base[1]) * emerald);
        const b = Math.round(colors.base[2] + (colors.accent[2] - colors.base[2]) * emerald);
        const alpha = (0.16 + depth * 0.84) * (0.7 + shimmer * 0.3) * alphaFade;
        const dotRadius = (0.55 + depth * 0.85) * (size / 132) * (1 + shimmer * 0.18);

        ctx.beginPath();
        ctx.arc(px, py, dotRadius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
        ctx.fill();
      }

      if (exit >= 1 && !doneRef.current) {
        doneRef.current = true;
        if (rootRef.current) rootRef.current.style.display = "none";
        return;
      }
      frame = requestAnimationFrame(draw);
    };

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [dark, size]);

  return (
    <div
      ref={rootRef}
      className={`inline-flex flex-col items-center gap-3 ${className}`}
      role="status"
      aria-live="polite"
      aria-label={displayLabel}
    >
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className="block shrink-0"
        aria-hidden="true"
      />
      <span className="chat-ink rounded-full border border-border/70 bg-surface-2/70 px-3 py-1 text-[11px] font-medium tracking-wide">
        {displayLabel}
      </span>
    </div>
  );
}

export default ThinkingOrb;
