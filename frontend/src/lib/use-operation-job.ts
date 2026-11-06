'use client';

import { useEffect, useRef, useState } from 'react';
import { api, OperationJob } from '@/lib/api';

export function useOperationPoller(
  jobId: string | null,
  onTerminal?: (job: OperationJob) => void,
) {
  const [job, setJob] = useState<OperationJob | null>(null);
  const onTerminalRef = useRef(onTerminal);

  useEffect(() => {
    onTerminalRef.current = onTerminal;
  });

  useEffect(() => {
    if (!jobId) {
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const next = await api.getOperation(jobId);
        if (cancelled) return;
        setJob(next);
        if (
          next.status === 'completed' ||
          next.status === 'failed' ||
          next.status === 'cancelled'
        ) {
          onTerminalRef.current?.(next);
          return;
        }
        timer = setTimeout(poll, 1000);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 2000);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  return job;
}

export async function pollOperation(
  jobId: string,
  onUpdate: (job: OperationJob) => void,
  signal?: AbortSignal,
): Promise<OperationJob> {
  while (true) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const job = await api.getOperation(jobId);
    onUpdate(job);
    if (
      job.status === 'completed' ||
      job.status === 'failed' ||
      job.status === 'cancelled'
    ) {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}
