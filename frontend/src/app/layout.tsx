import type { Metadata, Viewport } from "next";
import { Oxanium, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});
import { Providers } from "./providers";
import { REVORA, getSiteUrl, isIndexableDeployment } from "@/lib/site";
import { buildStructuredData } from "@/lib/structured-data";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const oxanium = Oxanium({
  subsets: ["latin"],
  variable: "--font-oxanium",
  display: "swap",
});

const siteTitle = `${REVORA.systemName} | ${REVORA.tagline}`;
const googleSiteVerification = process.env.GOOGLE_SITE_VERIFICATION?.trim();

/**
 * Global metadata.
 *
 * `metadataBase` points at the canonical production origin (never at a preview
 * deployment), so relative URLs such as the sitemap entries resolve correctly.
 * The canonical URL itself is intentionally NOT set here: each page declares its own
 * (`/` in the marketing route group), so no page can be accidentally canonicalised to
 * the homepage.
 */
export const metadata: Metadata = {
  metadataBase: new URL(getSiteUrl()),
  applicationName: REVORA.name,
  title: {
    default: siteTitle,
    template: `%s | ${REVORA.name}`,
  },
  description: REVORA.description,
  authors: [{ name: "Revora Team", url: REVORA.github.repo }],
  creator: "Revora Team",
  publisher: REVORA.name,
  category: "technology",
  openGraph: {
    type: "website",
    siteName: REVORA.systemName,
    title: siteTitle,
    description: REVORA.description,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: REVORA.description,
  },
  robots: isIndexableDeployment()
    ? {
        index: true,
        follow: true,
        googleBot: {
          index: true,
          follow: true,
          "max-image-preview": "large",
          "max-snippet": -1,
          "max-video-preview": -1,
        },
      }
    : {
        // Preview deployments stay out of the index entirely.
        index: false,
        follow: false,
      },
  ...(googleSiteVerification ? { verification: { google: googleSiteVerification } } : {}),
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0b12" },
  ],
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
                const isAdmin = (window.location.pathname || '').startsWith('/admin');
                if (isAdmin) {
                  const stored = localStorage.getItem('revora-admin-theme');
                  const theme = stored ? JSON.parse(stored).state.theme : 'dark';
                  document.documentElement.classList.add(theme === 'dark' ? 'admin-dark' : 'admin-light');
                } else {
                  const stored = localStorage.getItem('revora-theme');
                  let theme = 'dark';
                  if (stored) {
                    theme = JSON.parse(stored).state.theme;
                  } else if (window.matchMedia('(prefers-color-scheme: light)').matches) {
                    theme = 'light';
                  }
                  document.documentElement.classList.add(theme);
                }
              } catch (e) {}
            `,
          }}
        />
      </head>
      <body className={`${inter.variable} ${oxanium.variable} ${jetbrainsMono.variable} min-h-screen bg-background text-foreground antialiased font-sans`} suppressHydrationWarning>
        <Providers>
          {children}
        </Providers>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(buildStructuredData()) }}
        />
        {/*
          Dev-only design-helper script. It must never reach a production build: besides
          being useless there, it exposes a local helper endpoint and token in the HTML.
        */}
        {process.env.NODE_ENV === "development" && (
          <>
                      </>
        )}

</body>
    </html>
  );
}
