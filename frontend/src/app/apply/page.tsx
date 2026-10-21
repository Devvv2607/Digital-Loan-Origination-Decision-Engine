import type { Metadata } from "next";

import { ApplyFlow } from "@/components/apply/flow";

export const metadata: Metadata = { title: "Apply — Lendwise (Demo)" };

export default function ApplyPage() {
  return <ApplyFlow />;
}
