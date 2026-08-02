import type { Metadata } from "next";
import { Oxanium, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

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
      <body className={`${inter.variable} ${oxanium.variable} min-h-screen bg-background text-foreground antialiased font-sans`} suppressHydrationWarning>
        <Providers>
          {children}
        </Providers>
      {/* impeccable-live-start */}
<script src="http://localhost:8400/live.js?token=4652ea2d-e03b-4190-a7cf-9e1e48c88b51"></script>
{/* impeccable-live-end */}
</body>
    </html>
  );
}
