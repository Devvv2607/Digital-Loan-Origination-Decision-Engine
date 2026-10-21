"use client";

import { useEffect, useState } from "react";
import { Check, Minus } from "lucide-react";

import { OutcomeMark } from "@/components/outcome-mark";
import { ApiError, api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { DecisionView } from "@/lib/types";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, StepShell } from "../ui";

const HEADLINES = {
  APPROVED: "You're approved",
  REFERRED: "Your application is with our credit team",
  DECLINED: "We can't offer you a loan right now",
} as const;

const NEXT = {
  APPROVED: "Your offer is ready. Read the key facts, including the full cost, before you decide.",
  REFERRED:
    "A credit analyst will look at your application and approve or decline it. In this demo nothing is sent to you; an analyst works through the referral queue.",
  DECLINED:
    "You can apply again later. If something changes, such as your income or existing loans, a new application may get a different result.",
} as const;

export function DecisionStep({ ctx }: { ctx: FlowContext }) {
  const [decision, setDecision] = useState<DecisionView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<DecisionView>(`/applications/${ctx.session.applicationId}/decision`, { token: ctx.session.token })
      .then(({ data }) => setDecision(data))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load your decision."));
  }, [ctx.session.applicationId, ctx.session.token]);

  if (error) return <ErrorNotice message={error} />;
  if (!decision) return <p className="text-muted-foreground">Loading your decision</p>;

  const app = ctx.app;
  const trace: [string, boolean, string][] = [
    ["PAN verified", true, app?.pan.masked ?? ""],
    ["e-KYC complete", true, "Name, date of birth and address confirmed"],
    app?.aa.status === "APPROVED"
      ? ["Bank data shared", true, "Income checked against 6 months of credits"]
      : ["Bank data not shared", false, "Declared income used"],
    ["Credit bureau report requested", true, "From the simulated bureau"],
  ];

  return (
    <StepShell title={HEADLINES[decision.outcome]}>
      <div className="rounded-xl border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
          <OutcomeMark outcome={decision.outcome} />
          <p className="text-sm text-muted-foreground">
            Decided {dateTime(decision.created_at)}
            {decision.decided_by === "analyst" ? " by a credit analyst" : ""}
          </p>
        </div>

        {decision.reasons.length > 0 ? (
          <div className="px-5 py-4">
            <h2 className="text-sm font-semibold">{decision.outcome === "APPROVED" ? "Good to know" : "Why"}</h2>
            <ul className="mt-2 space-y-2 text-[0.95rem]">
              {decision.reasons.map((r) => (
                <li key={r.message} className="border-l-2 border-primary/40 pl-3">
                  {r.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="border-t border-border px-5 py-4">
          <h2 className="text-sm font-semibold">What we checked</h2>
          <ul className="mt-2 space-y-2 text-sm">
            {trace.map(([label, done, detail]) => (
              <li key={label} className="flex gap-2.5">
                {done ? (
                  <Check className="mt-0.5 size-4 shrink-0 text-approve" aria-hidden />
                ) : (
                  <Minus className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                )}
                <span>
                  <span className="font-medium">{label}</span>
                  <span className="text-muted-foreground">. {detail}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            Decided under credit policy version {decision.policy_version}.
          </p>
        </div>
      </div>

      <p className="text-[0.95rem] leading-relaxed">{NEXT[decision.outcome]}</p>

      {decision.outcome === "APPROVED" ? (
        <ActionButton onClick={() => ctx.refresh()}>Review your offer</ActionButton>
      ) : (
        <ActionButton variant="outline" onClick={ctx.startOver}>
          Start a new application
        </ActionButton>
      )}
    </StepShell>
  );
}
