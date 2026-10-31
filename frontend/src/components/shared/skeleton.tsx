function Shimmer({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`animate-pulse rounded-xl bg-surface-2 ${className ?? ''}`}
      style={style}
    />
  );
}

export function SkeletonCard({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <Shimmer key={i} className="h-28 p-6" />
      ))}
    </div>
  );
}

export function SkeletonList({ count = 3, height = 'h-20' }: { count?: number; height?: string }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <Shimmer key={i} className={`${height} rounded-xl`} />
      ))}
    </div>
  );
}

export function SkeletonText({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: lines }).map((_, i) => (
        <Shimmer key={i} className="h-4 rounded" style={{ width: `${85 - i * 10}%` }} />
      ))}
    </div>
  );
}
