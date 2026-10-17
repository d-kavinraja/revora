import { FlaskConical } from 'lucide-react';

export function ComingSoonCard() {
  return (
    <article
      aria-label="More models coming soon"
      className="h-full flex flex-col items-center justify-center text-center rounded-xl border border-dashed border-border bg-surface-1 p-6 md:p-8"
    >
      <span className="w-14 h-14 rounded-full bg-surface-2 text-muted-foreground flex items-center justify-center mb-4">
        <FlaskConical size={22} aria-hidden="true" />
      </span>
      <h2 className="font-semibold text-base tracking-tight">More models coming soon</h2>
      <p className="mt-1.5 text-sm text-foreground/70 leading-relaxed max-w-[36ch]">
        We&rsquo;re training new models to expand what you can test.
      </p>
      <p className="mt-2 text-xs text-muted-foreground">Stay tuned.</p>
    </article>
  );
}
