"use client";

import { useSyncExternalStore } from "react";
import type { BjorkTone } from "./palette";

function getToneSnapshot(): BjorkTone {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function getServerTone(): BjorkTone {
  return "dark";
}

function subscribeTone(callback: () => void) {
  if (typeof document === "undefined") return () => {};
  const root = document.documentElement;
  const observer = new MutationObserver(callback);
  observer.observe(root, { attributes: true, attributeFilter: ["class"] });

  const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
  mq?.addEventListener?.("change", callback);

  return () => {
    observer.disconnect();
    mq?.removeEventListener?.("change", callback);
  };
}

export function useBjorkTone(tone?: BjorkTone): BjorkTone {
  const detected = useSyncExternalStore(subscribeTone, getToneSnapshot, getServerTone);
  return tone ?? detected;
}
