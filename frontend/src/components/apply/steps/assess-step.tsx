"use client";

import { useRef, useState } from "react";

import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { inr, months } from "@/lib/format";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, StepShell } from "../ui";

export function AssessStep({ ctx }: { ctx: FlowContext }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const d = ctx.app?.details;
  const sharedBankData = ctx.app?.aa.status === "APPROVED";

  async function assess() {
    setError(null);
    setBusy(true);
    try {
      await api(`/applications/${ctx.session.applicationId}/assess`, {
        method: "POST",
        token: ctx.session.token,
        idempotencyKey: key.current,
      });
      await ctx.refresh();
      ctx.showDecision();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't get a decision. Please try again.");
      setBusy(false);
    }
  }

  return (
    <StepShell
      title="Ready for your decision"
      intro="Most applications get an answer straight away. Some go to a credit analyst for a closer look."
    >
      {d ? (
        <dl className="divide-y divide-border rounded-lg border border-border bg-card text-[0.95rem]">
          <Row k="Loan" v={`${inr(d.loan_amount ?? 0)} over ${months(d.tenure_months ?? 0)}`} />
          <Row k="Income" v={`${inr(d.declared_monthly_income ?? 0)} a month, ${sharedBankData ? "to be checked against your bank data" : "as you declared it"}`} />
          <Row k="Identity" v="PAN and e-KYC verified" />
        </dl>
      ) : null}
      <p className="text-sm text-muted-foreground">
        Next we fetch your report from a simulated credit bureau, then run 6 eligibility rules and our fraud checks.
      </p>
      <ErrorNotice message={error} />
      <ActionButton busy={busy} busyLabel="Checking your credit history and running the decision" onClick={assess}>
        Get my decision
      </ActionButton>
    </StepShell>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-3 px-4 py-3">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="figures">{v}</dd>
    </div>
  );
}
