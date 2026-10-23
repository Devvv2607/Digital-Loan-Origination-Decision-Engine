"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { dateTime, inr, months } from "@/lib/format";
import type { AppState, MyApplications, NextStep } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Notice, StepShell } from "../ui";
import { PURPOSES } from "./details-step";

const STATUS: Record<AppState, { label: string; className: string }> = {
  DRAFT: { label: "Draft", className: "bg-muted text-foreground" },
  KYC_PENDING: { label: "Verification in progress", className: "bg-muted text-foreground" },
  UNDER_ASSESSMENT: { label: "Being assessed", className: "bg-muted text-foreground" },
  APPROVED: { label: "Approved", className: "bg-approve-soft text-foreground" },
  REFERRED: { label: "Under review", className: "bg-refer-soft text-foreground" },
  DECLINED: { label: "Not approved", className: "bg-decline-soft text-foreground" },
  DISBURSED: { label: "Disbursed", className: "bg-approve-soft text-foreground" },
  EXPIRED: { label: "Expired", className: "bg-muted text-muted-foreground" },
};

const NEXT: Record<NextStep, string> = {
  DETAILS: "Fill in your details",
  SUBMIT: "Submit your details",
  PAN: "Verify your PAN",
  EKYC: "Complete e-KYC",
  AA_CONSENT: "Choose whether to share bank data",
  ASSESS: "Get your decision",
  OFFER: "Review your offer",
  ESIGN: "E-sign your loan agreement",
  DISBURSE: "Receive the money",
  UNDER_REVIEW: "Wait for a credit analyst's review",
  DECISION: "See the decision",
  DONE: "Nothing. Your loan has been disbursed.",
  START_NEW: "Start a new application",
};

const PURPOSE_LABEL = Object.fromEntries(PURPOSES);
const IN_PROGRESS: AppState[] = ["DRAFT", "KYC_PENDING", "UNDER_ASSESSMENT", "APPROVED"];

/** US-09 enhancement: every application on this phone number, with its status and next step. */
export function ApplicationsStep({ ctx }: { ctx: FlowContext }) {
  const [data, setData] = useState<MyApplications | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<MyApplications>("/applications", { token: ctx.session.token })
      .then(({ data }) => setData(data))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) {
          ctx.signOut();
          return;
        }
        setError(e instanceof ApiError ? e.message : "Couldn't load your applications.");
      });
    // Load once when the screen opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startNew() {
    setBusy(true);
    setError(null);
    try {
      await ctx.newApplication(ctx.session.token!);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start your application.");
      setBusy(false);
    }
  }

  return (
    <StepShell title="My applications" intro="Applications on this mobile number, most recent first.">
      <ErrorNotice message={error} />
      {data === null && !error ? <p className="text-muted-foreground">Loading your applications</p> : null}
      {data ? (
        <>
          {data.items.length > 0 ? (
            <ul className="space-y-3">
              {data.items.map((a) => {
                const status = STATUS[a.state];
                const title = [
                  a.loan_amount ? inr(a.loan_amount) : "Amount not chosen yet",
                  a.tenure_months ? months(a.tenure_months) : null,
                  a.purpose ? PURPOSE_LABEL[a.purpose] ?? null : null,
                ]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <li key={a.id} className="rounded-lg border border-border bg-card px-4 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
                      <div className="min-w-0 space-y-1 text-sm">
                        <p className="figures font-medium text-[0.95rem]">{title}</p>
                        <p>
                          <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", status.className)}>
                            {status.label}
                          </span>
                        </p>
                        <p>
                          <span className="text-muted-foreground">Next: </span>
                          {NEXT[a.next_step]}
                        </p>
                        {a.kyc_reused ? (
                          <p className="flex items-center gap-1.5 text-muted-foreground">
                            <ShieldCheck className="size-4 text-approve" aria-hidden />
                            KYC already verified
                          </p>
                        ) : null}
                        <p className="text-muted-foreground">Last updated {dateTime(a.last_activity_at)}</p>
                      </div>
                      {a.state !== "EXPIRED" ? (
                        <ActionButton
                          variant={IN_PROGRESS.includes(a.state) ? "default" : "outline"}
                          className="sm:w-auto"
                          aria-label={`${IN_PROGRESS.includes(a.state) ? "Continue" : "View"} application: ${title}`}
                          onClick={() => ctx.openApplication(a.id)}
                        >
                          {IN_PROGRESS.includes(a.state) ? "Continue" : "View"}
                        </ActionButton>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-muted-foreground">You don&apos;t have any applications yet.</p>
          )}
          {data.kyc_on_file ? (
            <Notice tone="approve" title="KYC already verified">
              You completed e-KYC on an earlier application. Apply again with the same PAN and you won&apos;t need
              to repeat it.
            </Notice>
          ) : null}
          <div>
            <ActionButton
              variant={data.items.some((a) => IN_PROGRESS.includes(a.state)) ? "outline" : "default"}
              busy={busy}
              busyLabel="Starting your application"
              onClick={startNew}
            >
              Start a new application
            </ActionButton>
          </div>
          <p className="text-sm text-muted-foreground">
            Applications left untouched for 30 days expire, and offers close 7 days after they&apos;re made.
          </p>
        </>
      ) : null}
    </StepShell>
  );
}
