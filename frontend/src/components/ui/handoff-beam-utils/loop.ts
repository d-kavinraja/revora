"use client";

import { useEffect, useRef, type RefObject } from "react";

interface LoopOptions {
  fpsCap?: number;
}

export function useVisibleLoop(
  ref: RefObject<Element | null>,
  frame: (dt: number) => void,
  options: LoopOptions = {},
) {
  const frameRef = useRef(frame);
  const fpsCapRef = useRef(options.fpsCap ?? 0);

  useEffect(() => {
    frameRef.current = frame;
    fpsCapRef.current = options.fpsCap ?? 0;
  }, [frame, options.fpsCap]);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof window === "undefined") return;

    let raf = 0;
    let last = performance.now();
    let acc = 0;
    let visible = typeof IntersectionObserver === "undefined";

    const tick = (now: number) => {
      const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
      last = now;

      const fpsCap = fpsCapRef.current;
      if (!visible) {
        raf = requestAnimationFrame(tick);
        return;
      }

      if (fpsCap > 0) {
        acc += dt;
        const step = 1 / fpsCap;
        if (acc >= step) {
          acc = acc % step;
          frameRef.current(step);
        }
      } else {
        frameRef.current(dt);
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame((now) => {
      last = now;
      raf = requestAnimationFrame(tick);
    });

    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        (entries) => {
          visible = entries.some((entry) => entry.isIntersecting);
        },
        { threshold: 0.01 },
      );
      observer.observe(node);
    }

    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
    };
  }, [ref]);
}
