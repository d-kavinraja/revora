'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const TABS = [
  { href: '/admin/hosted-ollama', label: 'Models' },
  { href: '/admin/hosted-ollama/speech', label: 'Speech' },
];

export function HostedTabs() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Hosted model sections"
      className="mb-6 flex items-center gap-1 overflow-x-auto border-b border-border"
    >
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? 'page' : undefined}
            className={`-mb-px inline-flex h-11 items-center whitespace-nowrap border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
              active
                ? 'border-brand text-brand'
                : 'border-transparent text-foreground/70 hover:text-foreground'
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
