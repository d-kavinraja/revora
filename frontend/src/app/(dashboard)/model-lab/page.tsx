import Link from 'next/link';
import { ArrowRight, Brain, FlaskConical } from 'lucide-react';

interface LabModel {
  id: string;
  name: string;
  version: string;
  task: string;
  inputs: string;
  href: string;
}

// Revora's own trained models. Append future models here — each entry maps
// to a dedicated testing route. Nothing here implies third-party BYOK
// providers, which live under Settings.
const MODELS: LabModel[] = [
  {
    id: 'mouthmap',
    name: 'MouthMap Model',
    version: 'v1',
    task: 'Lip-reading from short video clips — upload or pick a test video to inspect predictions.',
    inputs: 'MP4 · WebM · MPG up to 50MB',
    href: '/model-lab/mouthmap',
  },
];

export default function ModelLabPage() {
  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 space-y-5 md:space-y-6">
      <nav aria-label="Breadcrumb" className="text-xs text-foreground/60">
        <Link href="/dashboard" className="hover:text-foreground transition-colors">
          Home
        </Link>
        <span className="mx-1.5" aria-hidden="true">
          &gt;
        </span>
        <span aria-current="page" className="text-foreground font-medium">
          Model Lab
        </span>
      </nav>

      <div>
        <h1 className="text-2xl md:text-[1.75rem] font-bold tracking-tight">Model Lab</h1>
        <p className="text-foreground/75 text-sm mt-2 leading-relaxed">
          Explore and test Revora&apos;s own trained AI models, free to use.
        </p>
      </div>

      <div className="grid gap-4 md:gap-5 md:grid-cols-2">
        {MODELS.map((m) => (
          <Link
            key={m.id}
            href={m.href}
            className="rounded-xl border border-border bg-surface-1 p-4 md:p-5 flex flex-col transition-colors hover:border-brand/30 group"
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="w-8 h-8 rounded-lg bg-brand/10 text-brand flex items-center justify-center shrink-0">
                <Brain size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold text-[15px] tracking-tight leading-tight flex items-center gap-2 flex-wrap">
                  {m.name}
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-brand/20 text-brand border border-brand/30">
                    {m.version}
                  </span>
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/30">
                    Available
                  </span>
                </h2>
              </div>
            </div>
            <p className="text-[13px] text-foreground/70 leading-relaxed">{m.task}</p>
            <p className="text-xs text-foreground/65 mt-2">Input: {m.inputs}</p>
            <span className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand">
              Open model
              <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </span>
          </Link>
        ))}

        <div className="rounded-xl border border-dashed border-border bg-surface-1 p-4 md:p-5 flex flex-col justify-center">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-8 h-8 rounded-lg bg-surface-2 text-muted-foreground flex items-center justify-center shrink-0">
              <FlaskConical size={16} />
            </span>
            <h2 className="font-semibold text-[15px] tracking-tight leading-tight text-foreground/75">
              More models coming soon
            </h2>
          </div>
          <p className="text-[13px] text-foreground/70 leading-relaxed">
            New Revora-trained models will appear here as they become available.
          </p>
        </div>
      </div>

      <p className="text-xs text-foreground/60 leading-relaxed max-w-[70ch]">
        Free to try with your Revora account — no API key or payment. Fair-use limits apply
        (50MB videos, best-effort availability; retries expected during peak or cold starts).
      </p>
    </div>
  );
}
