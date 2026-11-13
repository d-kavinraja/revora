export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (!Number.isFinite(diff)) return '';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function toDate(dateStr: string | null): Date | null {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(dateStr: string | null): string {
  const date = toDate(dateStr);
  if (!date) return '';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export function formatDateTimeShort(dateStr: string | null): string {
  const date = toDate(dateStr);
  if (!date) return '';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export function formatDateTimeWithRelative(dateStr: string | null): string {
  const relative = timeAgo(dateStr);
  const absolute = formatDateTime(dateStr);
  if (!relative || !absolute) return absolute;
  return `${relative} (${absolute})`;
}

/** Local value for an <input type="datetime-local">. */
export function toDatetimeLocalValue(iso: string | null): string {
  const date = toDate(iso);
  if (!date) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** ISO value for an API payload, or null when the field is cleared. */
export function fromDatetimeLocalValue(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function formatWindow(
  startsAt: string | null,
  endsAt: string | null,
): string {
  if (!startsAt && !endsAt) return 'Always on';
  if (startsAt && !endsAt) return `Starts ${formatDateTime(startsAt)}`;
  if (!startsAt && endsAt) return `Ends ${formatDateTime(endsAt)}`;
  return `${formatDateTimeShort(startsAt)} to ${formatDateTimeShort(endsAt)}`;
}
