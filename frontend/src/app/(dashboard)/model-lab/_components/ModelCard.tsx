import Link from 'next/link';
import { ArrowRight, Network, Video } from 'lucide-react';

export function ModelCard() {
  return (
    <article className="h-full flex flex-col rounded-xl border border-border bg-surface-1 shadow-sm md:shadow-lg shadow-black/5 p-5 md:p-6 transition-colors hover:border-brand/30">
      {/* Icon + title + badges */}
      <div className="flex items-center gap-3.5">
        <span className="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center text-white ring-1 ring-inset ring-white/20 shadow-[0_0_16px_rgba(8,126,173,0.3)]" style={{ background: '#087EAD' }}>
          <svg
            viewBox="0 0 64 64"
            width="26"
            height="26"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            stroke="#FFFFFF"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10 22V13a3 3 0 0 1 3-3h9" />
            <path d="M42 10h9a3 3 0 0 1 3 3v9" />
            <path d="M54 42v9a3 3 0 0 1-3 3h-9" />
            <path d="M22 54h-9a3 3 0 0 1-3-3v-9" />
            <path d="M16 32 C21 31 25 25 32 25 C39 25 43 31 48 32 C43 33 38 40 32 40 C26 40 21 33 16 32Z" />
            <path d="M16 32C22 32 26 35 32 35 C38 35 42 32 48 32" />
            <path d="M23 46h18" opacity="0.8" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-base tracking-tight leading-tight">MouthMap Model</h2>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-surface-2 border border-border text-foreground/70">
              v1
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full bg-success/10 border border-success/30 text-success">
              <span className="w-1.5 h-1.5 rounded-full bg-success" aria-hidden="true" />
              Available
            </span>
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="mt-4 text-sm text-foreground/70 leading-relaxed">
        Lip-reading model that predicts spoken text from short video clips of mouth movements.
      </p>

      {/* Divider */}
      <div className="border-t border-border my-4" role="presentation" />

      {/* Input info row */}
      <p className="flex items-center gap-2 text-xs text-foreground/65">
        <Video size={14} className="shrink-0 text-ai-cyan" aria-hidden="true" />
        <span>
          Input: Short video clips (.mp4, .webm, .mpg) &bull; Max 50 MB per clip
        </span>
      </p>

      {/* Full-width CTA pinned to the card bottom for equal card heights */}
      <div className="mt-auto pt-4">
        <Link
          href="/model-lab/mouthmap"
          className="group inline-flex w-full items-center justify-center gap-2 h-11 px-4 rounded-xl bg-gradient-to-r from-[#4f46e5] to-[#7c3aed] text-white text-sm font-semibold transition-all duration-150 hover:brightness-110 hover:shadow-[0_0_24px_rgba(147,51,234,0.3)] active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1"
        >
          Open model
          <ArrowRight
            size={15}
            aria-hidden="true"
            className="transition-transform duration-150 group-hover:translate-x-0.5"
          />
        </Link>
      </div>
    </article>
  );
}
