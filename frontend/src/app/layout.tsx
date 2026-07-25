import type { Metadata } from "next";
import { Oxanium, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Footer } from "@/components/ui/footer";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const oxanium = Oxanium({
  subsets: ["latin"],
  variable: "--font-oxanium",
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Revora | AI-Powered Software Engineering Platform",
  description: "Next-generation PR reviews, security analysis, and performance tracking.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                const stored = localStorage.getItem('revora-theme');
                let theme = 'dark';
                if (stored) {
                  theme = JSON.parse(stored).state.theme;
                } else if (window.matchMedia('(prefers-color-scheme: light)').matches) {
                  theme = 'light';
                }
                document.documentElement.classList.add(theme);
              } catch (e) {}
            `,
          }}
        />
      </head>
      <body className={`${inter.variable} ${oxanium.variable} min-h-screen flex flex-col bg-background text-foreground antialiased font-sans`} suppressHydrationWarning>
        <Providers>
          <main className="flex-1 flex flex-col w-full h-full">
            {children}
          </main>
          <Footer logoSrc="/icon.png" />
        </Providers>
      </body>
    </html>
  );
}
