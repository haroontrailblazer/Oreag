import type { Metadata } from "next";
import { Geist_Mono, Inter } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

import { ogImagePath, ogImages } from "@/lib/og-image";
import { cn } from "@/lib/utils";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const ogImage = ogImagePath();

export const metadata: Metadata = {
  metadataBase: new URL("https://oreag.vercel.app"),
  title: "Oreag - RAG & Memory as a Service",
  description:
    "Turn your documents into a queryable RAG API with a built-in memory graph: upload, tune chunking and embeddings, and get a per-project endpoint.",
  // Favicons come from the app/ file conventions: icon.png + favicon.ico (both
  // the Oreag 3D app-icon badge, matching the landing brand mark). The
  // OG/Twitter image is public/oreag-og-whatsapp-v3.jpg (regenerate with
  // `node scripts/generate-og.mjs`); its ?v= is a hash of the file's own bytes,
  // so replacing the artwork changes the URL and social platforms re-fetch it.
  // See lib/og-image.
  //
  // NO `url:` here on purpose. It sets og:url, which crawlers read as the
  // page's CANONICAL address - and because this is the root layout, every page
  // inherits it. A hardcoded value made /docs announce the homepage as its own
  // canonical URL. It also does nothing for WhatsApp's cache, which is keyed on
  // the link the user actually pasted, not on og:url.
  openGraph: {
    title: "Oreag - RAG & Memory as a Service",
    description:
      "Turn your documents into a queryable RAG API with a built-in memory graph.",
    siteName: "Oreag",
    type: "website",
    images: ogImages(),
  },
  twitter: {
    card: "summary_large_image",
    title: "Oreag - RAG & Memory as a Service",
    description:
      "Turn your documents into a queryable RAG API with a built-in memory graph.",
    images: [ogImage],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(
        "h-full font-sans antialiased",
        inter.variable,
        geistMono.variable
      )}
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider>
          {children}
          <Toaster position="bottom-right" offset={28} />
        </ThemeProvider>
      </body>
    </html>
  );
}
