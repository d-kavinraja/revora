import Link from "next/link";
import Image from "next/image";
import { buttonVariants } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";

interface HeaderProps {
  className?: string;
}

export function Header({ className }: HeaderProps) {
  return (
    <header className={cn("flex items-center justify-between p-6 z-50 border-b border-border bg-background/50 backdrop-blur-md sticky top-0 w-full", className)}>
      <div className="flex items-center gap-2.5">
        <Image
          src="/revora-logo.png"
          alt="Revora Logo"
          width={32}
          height={32}
          className="rounded-lg object-contain shrink-0 shadow-[0_0_16px_rgba(99,102,241,0.3)]"
        />
        <Link href="/" className="font-bold text-xl tracking-tight" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>
          Revora
        </Link>
      </div>
      <nav className="flex items-center gap-3">
        <ThemeToggle />
        <Link
          href="/login"
          className={cn(buttonVariants({ variant: "ghost" }), "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]")}
        >
          Sign In
        </Link>
        <Link
          href="/register"
          className={cn(buttonVariants({ variant: "default" }), "bg-foreground text-background hover:bg-foreground/90")}
        >
          Get Started
        </Link>
      </nav>
    </header>
  );
}
