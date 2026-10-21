import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Public_Sans, Source_Serif_4 } from "next/font/google";

import { DemoBanner } from "@/components/demo-banner";
import "./globals.css";

const publicSans = Public_Sans({ subsets: ["latin"], variable: "--font-public-sans", display: "swap" });
const sourceSerif = Source_Serif_4({ subsets: ["latin"], variable: "--font-source-serif", display: "swap" });

export const metadata: Metadata = {
  title: "Lendwise (Demo) — personal loan decisioning prototype",
  description:
    "Demo prototype of a digital personal-loan journey with simulated identity, credit and bank-data checks. Not affiliated with any bank or lender.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f6f8fa" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" className={`${publicSans.variable} ${sourceSerif.variable}`}>
      <body className="min-h-dvh flex flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <DemoBanner />
        <header className="border-b border-border bg-card">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-4">
            <Link href="/" className="flex h-11 items-center gap-1 text-[1.05rem] font-semibold tracking-tight text-foreground">
              Lendwise <span className="font-normal text-muted-foreground">(Demo)</span>
            </Link>
            <nav aria-label="Main" className="flex items-center gap-5 text-sm">
              <Link href="/apply" className="flex h-11 items-center px-2 text-foreground hover:text-primary">
                Apply
              </Link>
            </nav>
          </div>
        </header>
        <main id="main" className="flex-1">
          {children}
        </main>
        <footer className="border-t border-border">
          <div className="mx-auto w-full max-w-5xl px-4 py-6 text-sm text-muted-foreground">
            Lendwise (Demo) is a fictional lender built for a portfolio project. Every identity, credit and bank check
            on this site is simulated, and no real money moves.
          </div>
        </footer>
      </body>
    </html>
  );
}
