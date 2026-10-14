'use client';

import { JsonViewer } from './JsonViewer';

interface InferenceJsonCardProps {
  data: unknown | null;
  /** Grid span helper so the card fills the row before a result exists. */
  className?: string;
}

export function InferenceJsonCard({ data, className }: InferenceJsonCardProps) {
  return (
    <div className={className}>
      <JsonViewer
        title="Inference Output (JSON)"
        subtitle="Raw inference response payload"
        data={data}
        emptyText="Run inference to populate the raw response."
        className="h-full"
      />
    </div>
  );
}
