'use client';

import { useState, useRef, useEffect } from 'react';
import { CalendarIcon, XIcon } from 'lucide-react';

/* ─── Mini Calendar Picker ─── */
export function CalendarPicker({
  value,
  onChange,
  label,
  minDate,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  minDate?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Build the month grid
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth()); // 0-indexed

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstWeekday = new Date(viewYear, viewMonth, 1).getDay(); // 0=Sun
  const monthName = new Date(viewYear, viewMonth, 1).toLocaleString('default', { month: 'long' });

  const selected = value ? new Date(value + 'T00:00:00') : null;
  const minD = minDate ? new Date(minDate + 'T00:00:00') : null;

  const handleDayClick = (day: number) => {
    const m = String(viewMonth + 1).padStart(2, '0');
    const d = String(day).padStart(2, '0');
    onChange(`${viewYear}-${m}-${d}`);
    setOpen(false);
  };

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const displayValue = selected
    ? selected.toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })
    : label;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer whitespace-nowrap ${
          value
            ? 'bg-brand/10 border-brand/30 text-brand'
            : 'bg-surface-1 border-border text-muted-foreground hover:text-foreground hover:bg-white/[0.04]'
        }`}
      >
        <CalendarIcon size={12} />
        {displayValue}
      </button>

      {open && (
        <div className="absolute top-full mt-2 left-0 z-50 w-64 bg-surface-1 border border-border rounded-xl shadow-2xl p-3 animate-in fade-in-0 slide-in-from-top-2 duration-150">
          {/* Month nav */}
          <div className="flex items-center justify-between mb-3">
            <button onClick={prevMonth} className="p-1 rounded hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors text-sm">‹</button>
            <span className="text-sm font-semibold text-foreground">{monthName} {viewYear}</span>
            <button onClick={nextMonth} className="p-1 rounded hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors text-sm">›</button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 mb-1">
            {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(d => (
              <div key={d} className="text-center text-[10px] text-muted-foreground font-semibold py-1">{d}</div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-y-1">
            {Array.from({ length: firstWeekday }).map((_, i) => (
              <div key={`empty-${i}`} />
            ))}
            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1;
              const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
              const isSelected = selected &&
                selected.getFullYear() === viewYear &&
                selected.getMonth() === viewMonth &&
                selected.getDate() === day;
              const isDisabled = minD && new Date(dateStr + 'T00:00:00') < minD;
              const isToday =
                today.getFullYear() === viewYear &&
                today.getMonth() === viewMonth &&
                today.getDate() === day;

              return (
                <button
                  key={day}
                  disabled={!!isDisabled}
                  onClick={() => handleDayClick(day)}
                  className={`w-full aspect-square rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed ${
                    isSelected
                      ? 'bg-brand text-brand-foreground shadow-sm'
                      : isToday
                      ? 'border border-brand/40 text-brand hover:bg-brand/10'
                      : 'text-foreground hover:bg-white/[0.06]'
                  }`}
                >
                  {day}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Time Picker ─── */
export function TimePicker({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  const [hour, setHour] = useState('12');
  const [minute, setMinute] = useState('00');
  const [period, setPeriod] = useState<'AM' | 'PM'>('AM');

  const handleChange = (h: string, m: string, p: 'AM' | 'PM') => {
    setHour(h); setMinute(m); setPeriod(p);
    let h24 = parseInt(h, 10);
    if (p === 'AM' && h24 === 12) h24 = 0;
    if (p === 'PM' && h24 !== 12) h24 += 12;
    onChange(`${String(h24).padStart(2, '0')}:${m}`);
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</span>
      <select
        value={hour}
        onChange={e => handleChange(e.target.value, minute, period)}
        className="px-1.5 py-1 bg-surface-2 border border-border rounded text-xs text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
      >
        {Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, '0')).map(h => (
          <option key={h} value={h}>{h}</option>
        ))}
      </select>
      <span className="text-muted-foreground text-xs">:</span>
      <select
        value={minute}
        onChange={e => handleChange(hour, e.target.value, period)}
        className="px-1.5 py-1 bg-surface-2 border border-border rounded text-xs text-foreground focus:outline-none focus:border-brand/50 cursor-pointer"
      >
        {['00', '15', '30', '45'].map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <div className="flex rounded border border-border overflow-hidden">
        {(['AM', 'PM'] as const).map(p => (
          <button
            key={p}
            onClick={() => handleChange(hour, minute, p)}
            className={`px-2 py-1 text-[10px] font-semibold transition-colors cursor-pointer ${
              period === p ? 'bg-brand text-brand-foreground' : 'bg-surface-2 text-muted-foreground hover:text-foreground'
            }`}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ─── Date Range Filter Panel ─── */
export function DateRangeFilter({
  fromDate, toDate, fromTime, toTime, useTime,
  onFromDate, onToDate, onFromTime, onToTime, onToggleTime, onClear,
  className = "mb-6",
}: {
  fromDate: string; toDate: string; fromTime: string; toTime: string; useTime: boolean;
  onFromDate: (v: string) => void; onToDate: (v: string) => void;
  onFromTime: (v: string) => void; onToTime: (v: string) => void;
  onToggleTime: () => void; onClear: () => void;
  className?: string;
}) {
  const hasFilter = fromDate || toDate;

  return (
    <div className={`rounded-xl border transition-colors p-4 ${className} ${
      hasFilter ? 'border-brand/30 bg-brand/5' : 'border-border bg-surface-1'
    }`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CalendarIcon size={14} className={hasFilter ? 'text-brand' : 'text-muted-foreground'} />
          <span className="text-sm font-semibold text-foreground">Date Range Filter</span>
          {hasFilter && (
            <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-brand text-brand-foreground uppercase tracking-wide">Active</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Time toggle */}
          <label className="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground select-none">
            <div
              onClick={onToggleTime}
              className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${useTime ? 'bg-brand' : 'bg-surface-2 border border-border'}`}
            >
              <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${useTime ? 'left-4.5 translate-x-0' : 'left-0.5'}`} />
            </div>
            Time filter
          </label>
          {hasFilter && (
            <button onClick={onClear} className="text-xs text-muted-foreground hover:text-error flex items-center gap-1 transition-colors cursor-pointer">
              <XIcon size={12} />
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted-foreground font-medium">From</span>
          <CalendarPicker value={fromDate} onChange={onFromDate} label="Start date" />
          {useTime && fromDate && (
            <TimePicker value={fromTime} onChange={onFromTime} label="" />
          )}
        </div>

        {fromDate && (
          <>
            <span className="text-muted-foreground/50 text-sm">→</span>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-muted-foreground font-medium">To</span>
              <CalendarPicker value={toDate} onChange={onToDate} label="End date" minDate={fromDate} />
              {useTime && toDate && (
                <TimePicker value={toTime} onChange={onToTime} label="" />
              )}
            </div>
          </>
        )}
      </div>

      {fromDate && toDate && (
        <p className="mt-2.5 text-[11px] text-muted-foreground">
          Showing data from{' '}
          <span className="text-foreground font-medium">
            {new Date(fromDate).toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })}
            {useTime && fromTime ? ` ${fromTime}` : ''}
          </span>
          {' '}to{' '}
          <span className="text-foreground font-medium">
            {new Date(toDate).toLocaleDateString('default', { day: 'numeric', month: 'short', year: 'numeric' })}
            {useTime && toTime ? ` ${toTime}` : ''}
          </span>
        </p>
      )}
    </div>
  );
}
