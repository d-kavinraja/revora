import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Signing in',
  robots: { index: false, follow: false, nocache: true },
};

export default function AuthCallbackLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
