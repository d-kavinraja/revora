import { Header } from '@/components/layout/header';
import { Footer } from '@/components/ui/footer';

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen bg-background">
      <Header />
      <main className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
        {children}
      </main>
      <Footer logoSrc="/icon.png" className="z-20 relative bg-background/95 backdrop-blur-xl shadow-[0_-8px_30px_rgba(0,0,0,0.12)]" />
    </div>
  );
}
