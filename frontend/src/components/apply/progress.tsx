import { cn } from "@/lib/utils";

import type { OfferPhase, Stage } from "./flow";

const STEPS = ["Phone", "Details", "PAN", "e-KYC", "Bank data", "Decision", "Offer", "Sign and receive"] as const;

const INDEX: Record<Stage, number> = {
  loading: 0,
  phone: 0,
  details: 1,
  pan: 2,
  ekyc: 3,
  consent: 4,
  assess: 5,
  decision: 5,
  offer: 6,
  expired: 0,
  applications: 0,
};

/** Segmented progress for the 8-step journey. The current step is also announced as text. */
export function Progress({ stage, offerPhase }: { stage: Stage; offerPhase: OfferPhase }) {
  const done = stage === "offer" && offerPhase === "done";
  const current = done ? STEPS.length : stage === "offer" && offerPhase === "sign" ? 7 : INDEX[stage];
  if (stage === "loading" || stage === "expired" || stage === "applications") return <div className="h-[2.75rem]" aria-hidden />;
  return (
    <nav aria-label="Application progress">
      <p className="text-sm text-muted-foreground">
        {done ? (
          <span className="font-medium text-foreground">All {STEPS.length} steps complete</span>
        ) : (
          <>
            Step <span className="figures font-medium text-foreground">{current + 1}</span> of {STEPS.length}:{" "}
            <span className="font-medium text-foreground">{STEPS[current]}</span>
          </>
        )}
      </p>
      <ol className="mt-2 grid grid-cols-8 gap-1">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === current ? "step" : undefined}>
            <span className="sr-only">
              {label}
              {i < current ? " (done)" : i === current ? " (current)" : ""}
            </span>
            <span
              aria-hidden
              className={cn(
                "block h-1.5 rounded-full",
                i < current ? "bg-primary" : i === current ? "bg-primary/55" : "bg-border",
              )}
            />
          </li>
        ))}
      </ol>
    </nav>
  );
}
