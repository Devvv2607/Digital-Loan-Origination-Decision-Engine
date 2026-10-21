import { Check, Hourglass, X } from "lucide-react";

import { cn } from "@/lib/utils";

const OUTCOMES = {
  APPROVED: { label: "Approved", Icon: Check, cls: "border-approve/40 bg-approve-soft text-approve" },
  REFERRED: { label: "With our credit team", Icon: Hourglass, cls: "border-refer/40 bg-refer-soft text-refer" },
  DECLINED: { label: "Not approved", Icon: X, cls: "border-decline/40 bg-decline-soft text-decline" },
} as const;

/** Outcome badge used on the decision screen. Colour is never the only signal: icon and text too. */
export function OutcomeMark({ outcome, className }: { outcome: keyof typeof OUTCOMES; className?: string }) {
  const { label, Icon, cls } = OUTCOMES[outcome];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium",
        cls,
        className,
      )}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </span>
  );
}
