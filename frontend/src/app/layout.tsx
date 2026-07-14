import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://oreag.vercel.app"),
  title: "Oreag - RAG & Memory as a Service",
  description:
    "Turn your documents into a queryable RAG API with a built-in memory graph: upload, tune chunking and embeddings, and get a per-project endpoint.",
  // Favicons are picked up from the app/ file conventions: icon.png + favicon.ico
  // (both are the Oreag 3D app-icon badge, matching the landing brand mark).
  // The OG/Twitter image is the static public/og.png (regenerate with
  // `node scripts/generate-og.mjs`). A static asset resolves via metadataBase to
  // an absolute URL, is CDN-cached, and its .png path is exempt from the auth
  // middleware - so crawlers always get it.
  openGraph: {
    title: "Oreag - RAG & Memory as a Service",
    description:
      "Turn your documents into a queryable RAG API with a built-in memory graph.",
    url: "/",
    siteName: "Oreag",
    type: "website",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "Oreag - RAG & Memory as a Service",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Oreag - RAG & Memory as a Service",
    description:
      "Turn your documents into a queryable RAG API with a built-in memory graph.",
    images: ["/og.png"],
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
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
