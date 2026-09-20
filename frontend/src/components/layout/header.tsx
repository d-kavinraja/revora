import Link from "next/link";
import Image from "next/image";
import { buttonVariants } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";
import { REVORA } from "@/lib/site";

/**
 * GitHub mark. Inlined (like the other icon primitives in this codebase) so the header
 * stays a server component and no extra dependency is pulled in.
 */
const GithubMarkIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.05-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" /></svg>
);

interface HeaderProps {
  className?: string;
  hideThemeToggle?: boolean;
}

export function Header({ className, hideThemeToggle = false }: HeaderProps) {
  return (
    <header className={cn("flex items-center justify-between p-6 z-50 border-b border-border bg-background/50 backdrop-blur-md sticky top-0 w-full", className)}>
      <div className="flex items-center gap-2.5">
        <Image
          src="/revora-logo.png"
          alt="Revora Logo"
          width={32}
          height={32}
          className="rounded-lg object-contain shrink-0"
        />
        <Link href="/" className="font-bold text-xl tracking-tight" style={{ fontFamily: 'var(--font-oxanium, inherit)' }}>
          Revora
        </Link>
      </div>
      <nav className="flex items-center gap-3">
        {!hideThemeToggle && <ThemeToggle />}
        <a
          href={REVORA.github.repo}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Revora source code on GitHub"
          title="Revora source code on GitHub"
          className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]")}
        >
          <GithubMarkIcon />
        </a>
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
