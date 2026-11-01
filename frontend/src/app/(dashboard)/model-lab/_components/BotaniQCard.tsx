import Link from 'next/link';
import { ArrowRight, Leaf } from 'lucide-react';

export function BotaniQCard() {
  return (
    <article className="h-full flex flex-col rounded-xl border border-border bg-surface-1 shadow-sm md:shadow-lg shadow-black/5 p-5 md:p-6 transition-colors hover:border-emerald-500/30">
      {/* Icon + title + badges */}
      <div className="flex items-center gap-3.5">
        <span className="shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br from-[#059669] to-[#10b981] text-white flex items-center justify-center ring-1 ring-inset ring-white/20 shadow-[0_0_16px_rgba(16,185,129,0.3)]">
          <Leaf size={20} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-base tracking-tight leading-tight">BotaniQ Model</h2>
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
        Medicinal herb classifier that identifies plant and leaf species with confidence scores and top-5 ranked predictions.
      </p>

      {/* Divider */}
      <div className="border-t border-border my-4" role="presentation" />

      {/* Input info row */}
      <p className="flex items-center gap-2 text-xs text-foreground/65">
        <Leaf size={14} className="shrink-0 text-emerald-500" aria-hidden="true" />
        <span>
          Input: Images (.jpg, .png, .webp, .avif, .gif) or public URL &bull; Max 20 MB
        </span>
      </p>

      {/* CTA */}
      <div className="mt-auto pt-4">
        <Link
          href="/model-lab/botaniq"
          className="group inline-flex w-full items-center justify-center gap-2 h-11 px-4 rounded-xl bg-gradient-to-r from-[#059669] to-[#10b981] text-white text-sm font-semibold transition-all duration-150 hover:brightness-110 hover:shadow-[0_0_24px_rgba(16,185,129,0.3)] active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1"
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
