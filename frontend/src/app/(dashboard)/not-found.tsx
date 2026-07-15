import Link from 'next/link';
import { FolderIcon } from '@animateicons/react/lucide';

export default function DashboardNotFound() {
  return (
    <div className="w-full h-full flex items-center justify-center p-6">
      <div className="max-w-md w-full text-center space-y-4">
        <div className="w-16 h-16 bg-surface-2 text-muted-foreground rounded-full flex items-center justify-center mx-auto mb-4 border border-border">
          <FolderIcon size={32} />
        </div>
        <h2 className="text-2xl font-bold text-foreground">Page Not Found</h2>
        <p className="text-muted-foreground text-sm">
          We couldn&apos;t find what you were looking for. It might have been moved or deleted.
        </p>
        <Link
          href="/dashboard"
          className="inline-block mt-4 px-5 py-2.5 bg-brand hover:bg-brand-hover text-brand-foreground rounded-lg text-sm font-semibold transition-colors"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
