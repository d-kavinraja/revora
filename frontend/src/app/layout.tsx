import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

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
      <body className="min-h-screen bg-background text-foreground antialiased font-sans">
        <Providers>
          {children}
        </Providers>
      </body>
    </html>
  );
}
