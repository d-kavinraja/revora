"use client";

export function LiveRegion({ message }: { message: string }) {
  return (
    <span className="sr-only" aria-live="polite" aria-atomic="true">
      {message}
    </span>
  );
}
