"use client";

import { useState } from "react";

import { ApiError, api } from "@/lib/api";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Notice, StepShell } from "../ui";

const TERMS: [string, string][] = [
  ["Why", "To confirm your income for this loan application"],
  ["What", "Credits into your bank account over the last 6 months"],
  ["How often", "Once, for this application only"],
  ["Through", "A simulated Account Aggregator. No real bank is contacted."],
];

export function ConsentStep({ ctx }: { ctx: FlowContext }) {
  const [busy, setBusy] = useState<"APPROVE" | "DECLINE" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const suggested = ctx.session.persona?.aa_decision;

  async function decide(decision: "APPROVE" | "DECLINE") {
    setError(null);
    setBusy(decision);
    try {
      await api(`/applications/${ctx.session.applicationId}/aa/consent`, {
        method: "POST",
        token: ctx.session.token,
        body: { decision },
      });
      await ctx.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record your choice.");
      setBusy(null);
    }
  }

  return (
    <StepShell
      title="Share your bank data to verify income"
      intro="Sharing lets us confirm your income without asking for payslips or statements."
    >
      <dl className="divide-y divide-border rounded-lg border border-border bg-card text-[0.95rem]">
        {TERMS.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[5rem_1fr] gap-3 px-4 py-3 sm:grid-cols-[6.5rem_1fr]">
            <dt className="text-muted-foreground">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <Notice>
        If you don&apos;t share, we&apos;ll use the income you told us. Your application will then go to a credit
        analyst for review rather than getting an instant approval.
      </Notice>
      <ErrorNotice message={error} />
      <div className="flex flex-col gap-3 sm:flex-row">
        <ActionButton busy={busy === "APPROVE"} busyLabel="Fetching 6 months of bank data" disabled={busy !== null}
          onClick={() => decide("APPROVE")} variant={suggested === "DECLINE" ? "outline" : "default"}>
          Share bank data
        </ActionButton>
        <ActionButton busy={busy === "DECLINE"} busyLabel="Recording your choice" disabled={busy !== null}
          onClick={() => decide("DECLINE")} variant={suggested === "DECLINE" ? "default" : "outline"}>
          Continue without sharing
        </ActionButton>
      </div>
    </StepShell>
  );
}
