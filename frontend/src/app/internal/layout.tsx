import type { Metadata } from "next";

import { InternalShell } from "@/components/internal/shell";

export const metadata: Metadata = { title: "Internal tools — Lendwise (Demo)" };

export default function InternalLayout({ children }: { children: React.ReactNode }) {
  return <InternalShell>{children}</InternalShell>;
}
