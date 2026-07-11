import { type ReactNode } from 'react';

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-xl border border-dashed border-border p-16 text-center">
      <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center mx-auto mb-4 text-muted-foreground">
        {icon}
      </div>
      <p className="text-foreground font-medium">{title}</p>
      <p className="text-muted-foreground text-sm mt-1">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
