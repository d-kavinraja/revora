import type { Metadata } from 'next';
import { Header } from '@/components/layout/header';
import { Footer } from '@/components/ui/footer';

/**
 * Sign-in and registration belong to the application flow, not to public content, so
 * they are explicitly excluded from search results (and from the sitemap). They keep a
 * descriptive title for browser tabs and shares.
 */
export const metadata: Metadata = {
  title: 'Sign in or create an account',
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen bg-background">
      <Header />
      <main className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
        {children}
      </main>
      <Footer logoSrc="/revora-logo.png" className="z-20 relative bg-background/95 backdrop-blur-xl shadow-[0_-8px_30px_rgba(0,0,0,0.12)]" />
    </div>
  );
}
