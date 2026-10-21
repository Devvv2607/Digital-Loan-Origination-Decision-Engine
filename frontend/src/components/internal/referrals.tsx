"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ApiError, api, fieldErrors, newIdempotencyKey } from "@/lib/api";
import { dateTime, inr, months } from "@/lib/format";

import { useInternalAuth } from "./auth";
import { PageTitle } from "./shell";

interface QueueItem {
  application_id: string;
  applicant_name: string | null;
  phone_masked: string;
  pan_masked: string | null;
  primary_reason_code: string | null;
  reason_codes: string[];
  income_unverified: boolean;
  fraud_signal: boolean;
  requested_amount: number;
  referred_at: string;
  hours_in_queue: number;
}

const REASON_FILTERS = [
  "", "SYS_BUREAU_UNAVAILABLE", "DATA_INCOME_UNVERIFIED", "FRAUD_VELOCITY", "FRAUD_IDENTITY_MISMATCH",
  "FRAUD_INCOME_MISMATCH", "ELIG_SCORE_BORDERLINE", "ELIG_THIN_FILE", "ELIG_FOIR_HIGH", "ELIG_EMPLOYMENT_TENURE",
];
const PAGE_SIZE = 20;

function waiting(hours: number): string {
  if (hours < 1) return "under an hour";
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

export function ReferralQueue() {
  const { user } = useInternalAuth();
  const [page, setPage] = useState(1);
  const [reason, setReason] = useState("");
  const [data, setData] = useState<{ items: QueueItem[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    const q = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), ...(reason ? { reason_code: reason } : {}) });
    api<{ items: QueueItem[]; total: number }>(`/ops/referrals?${q}`, { token: user?.token })
      .then(({ data }) => setData(data))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load the queue."));
  }, [page, reason, user?.token]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  return (
    <>
      <PageTitle
        title="Referral queue"
        intro="Applications the engine sent for human review, oldest first. Open one to see every reason, the data behind it and the provider responses, then approve or decline with notes."
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="reason-filter" className="block text-sm font-medium">Reason</label>
          <select id="reason-filter" value={reason} onChange={(e) => { setReason(e.target.value); setPage(1); }}
            className="h-11 rounded-lg border border-input bg-card px-3 text-sm">
            {REASON_FILTERS.map((r) => <option key={r} value={r}>{r || "All reasons"}</option>)}
          </select>
        </div>
        {data ? <p className="pb-3 text-sm text-muted-foreground">{data.total} waiting</p> : null}
      </div>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {!data ? (
        <p className="text-muted-foreground">Loading the queue</p>
      ) : data.items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-input bg-card px-5 py-8 text-center">
          <p className="font-medium">No referrals waiting</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try the New to credit or Income mismatch applicant from the <Link className="text-primary underline" href="/#personas">home page</Link> to create one.
          </p>
        </div>
      ) : (
        <>
        <ul className="divide-y divide-border rounded-xl border border-border bg-card sm:hidden">
          {data.items.map((i) => (
            <li key={i.application_id} className="px-4 py-3 text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <Link href={`/internal/referrals/${i.application_id}`} className="font-medium text-primary underline-offset-2 hover:underline">
                  {i.applicant_name ?? "Unnamed"}
                </Link>
                <span className="figures shrink-0">{inr(i.requested_amount)}</span>
              </div>
              <p className="mt-1"><code className="text-xs">{i.primary_reason_code}</code>
                {i.reason_codes.length > 1 ? <span className="text-xs text-muted-foreground"> +{i.reason_codes.length - 1} more</span> : null}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                {i.fraud_signal ? <Flag>Fraud signal</Flag> : null}
                {i.income_unverified ? <Flag>Income unverified</Flag> : null}
                <span className="text-xs text-muted-foreground">Waiting {waiting(i.hours_in_queue)}</span>
              </div>
            </li>
          ))}
        </ul>
        <div className="hidden overflow-x-auto rounded-xl border border-border bg-card sm:block">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">Referred applications</caption>
            <thead className="border-b border-border text-left text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Applicant</th>
                <th scope="col" className="px-4 py-3 font-medium">Main reason</th>
                <th scope="col" className="px-4 py-3 font-medium">Flags</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Amount</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Waiting</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((i) => (
                <tr key={i.application_id} className="hover:bg-muted/50">
                  <td className="px-4 py-3">
                    <Link href={`/internal/referrals/${i.application_id}`} className="font-medium text-primary underline-offset-2 hover:underline">
                      {i.applicant_name ?? "Unnamed"}
                    </Link>
                    <span className="figures block text-xs text-muted-foreground">{i.phone_masked}, PAN {i.pan_masked}</span>
                  </td>
                  <td className="px-4 py-3">
                    <code className="text-xs">{i.primary_reason_code}</code>
                    {i.reason_codes.length > 1 ? (
                      <span className="block text-xs text-muted-foreground">+{i.reason_codes.length - 1} more</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {i.fraud_signal ? <Flag>Fraud signal</Flag> : null}
                      {i.income_unverified ? <Flag>Income unverified</Flag> : null}
                    </div>
                  </td>
                  <td className="figures px-4 py-3 text-right">{inr(i.requested_amount)}</td>
                  <td className="figures px-4 py-3 text-right">{waiting(i.hours_in_queue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
      {data && pages > 1 ? (
        <nav aria-label="Pages" className="mt-4 flex items-center gap-2 text-sm">
          <Button variant="outline" className="h-11 px-3" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span>Page {page} of {pages}</span>
          <Button variant="outline" className="h-11 px-3" disabled={page === pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </nav>
      ) : null}
    </>
  );
}

function Flag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-refer/40 bg-refer-soft px-2 py-0.5 text-xs text-refer">
      <AlertTriangle className="size-3" aria-hidden />
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- detail

interface Detail {
  application: {
    id: string;
    state: string;
    applicant_name: string | null;
    phone_masked: string;
    pan_masked: string | null;
    details: { employment_type: string; employer_name: string | null; months_in_current_job: number;
      declared_monthly_income: number; loan_amount: number; tenure_months: number; purpose: string };
    verification: { pan_status: string; pan_name_confirmation: string | null; kyc_status: string;
      kyc_pan_name_similarity: number | null; aa_status: string; aa_average_monthly_income: number | null };
  };
  decision: {
    reason_codes: string[];
    explanations: Record<string, string>;
    rule_results: { rule_id: string; result: string; code?: string; detail?: string }[];
    policy_version: number;
    inputs_snapshot: Record<string, unknown> & {
      bureau?: { available: boolean; ntc: boolean; score: number | null; existing_monthly_emis: number;
        active_loans: number; max_dpd_12m: number | null };
      inputs?: Record<string, unknown>;
    };
    created_at: string;
  };
  integration_results: { provider: string; operation: string; status: string; attempt: number; latency_ms: number;
    created_at: string }[];
  timeline: { event_type: string; from_state: string | null; to_state: string | null; actor: string; reason: string | null;
    created_at: string }[];
  review: { reviewer: string; action: string; notes: string; created_at: string } | null;
}

const RESULT_STYLE: Record<string, string> = {
  PASS: "text-approve", REFER: "text-refer", DECLINE: "text-decline", INFO: "text-muted-foreground",
  SKIPPED: "text-muted-foreground", NOT_EVALUATED: "text-muted-foreground",
};

export function ReferralDetail({ id }: { id: string }) {
  const { user } = useInternalAuth();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Detail>(`/ops/referrals/${id}`, { token: user?.token })
      .then(({ data }) => setD(data))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load this referral."));
  }, [id, user?.token]);
  useEffect(load, [load]);

  if (error) return <p role="alert" className="text-destructive">{error}</p>;
  if (!d) return <p className="text-muted-foreground">Loading the referral</p>;

  const a = d.application;
  const snap = d.decision.inputs_snapshot;
  const b = snap.bureau;
  const inputs = (snap.inputs ?? {}) as Record<string, unknown>;
  const facts: [string, string][] = [
    ["Requested", `${inr(a.details.loan_amount)} over ${months(a.details.tenure_months)}`],
    ["Employment", `${a.details.employment_type === "SALARIED" ? "Salaried" : "Self-employed"}, ${a.details.months_in_current_job} months${a.details.employer_name ? ` at ${a.details.employer_name}` : ""}`],
    ["Declared income", `${inr(a.details.declared_monthly_income)} a month`],
    ["Verified income", a.verification.aa_average_monthly_income ? `${inr(a.verification.aa_average_monthly_income)} a month (bank data)` : "Not shared (AA consent declined)"],
    ["Income used", snap.income_used !== undefined ? `${inr(Number(snap.income_used))} (${snap.income_source === "AA" ? "verified" : "declared"})` : "Not evaluated"],
    ["Bureau", !b?.available ? "Unavailable after 3 attempts" : b.ntc ? "No credit history" : `Score ${b.score}, EMIs ${inr(b.existing_monthly_emis)}, ${b.active_loans} active loans, max DPD ${b.max_dpd_12m ?? 0}`],
    ["Repayments / income (FOIR)", snap.foir !== undefined && snap.foir !== null ? `${(Number(snap.foir) * 100).toFixed(1)}%` : "Not evaluated"],
    ["Offer amount", snap.offer_amount !== undefined ? `${inr(Number(snap.offer_amount))} at ${snap.annual_rate}%` : "Not priced"],
    ["Applications in 24 h", inputs.applications_24h_phone !== undefined ? `${inputs.applications_24h_phone} by phone, ${inputs.applications_24h_device} by device` : "–"],
    ["Name match (PAN vs e-KYC)", a.verification.kyc_pan_name_similarity !== null ? a.verification.kyc_pan_name_similarity.toFixed(2) : "–"],
  ];

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/internal/referrals" className="text-primary underline-offset-2 hover:underline">Referral queue</Link>
      </p>
      <PageTitle title={a.applicant_name ?? "Applicant"} intro={`${a.phone_masked}, PAN ${a.pan_masked}. Currently ${a.state.toLowerCase().replace("_", " ")}.`} />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-6">
          <Section title="Why it was referred">
            <ul className="space-y-3">
              {d.decision.reason_codes.map((code) => (
                <li key={code} className="border-l-2 border-refer/50 pl-3">
                  <code className="text-xs font-semibold">{code}</code>
                  <p className="text-sm">{d.decision.explanations[code]}</p>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted-foreground">
              Engine decision {dateTime(d.decision.created_at)}, policy version {d.decision.policy_version}.
            </p>
          </Section>

          <Section title="Key facts">
            <dl className="divide-y divide-border text-sm">
              {facts.map(([k, v]) => (
                <div key={k} className="grid gap-1 py-2 sm:grid-cols-[13rem_1fr]">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="figures">{v}</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section title="Every rule and check">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-sm">
                <thead className="text-left text-muted-foreground">
                  <tr><th scope="col" className="py-2 pr-3 font-medium">Rule</th><th scope="col" className="py-2 pr-3 font-medium">Result</th><th scope="col" className="py-2 font-medium">Detail</th></tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {d.decision.rule_results.map((r) => (
                    <tr key={r.rule_id}>
                      <td className="figures py-2 pr-3 font-medium">{r.rule_id}</td>
                      <td className={`py-2 pr-3 font-medium ${RESULT_STYLE[r.result] ?? ""}`}>{r.result.replace("_", " ").toLowerCase()}</td>
                      <td className="py-2 text-muted-foreground">{r.detail ?? (r.result === "PASS" ? "Passed" : "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Provider calls (simulated)">
            <div className="overflow-x-auto">
              <table className="figures w-full min-w-[32rem] text-sm">
                <thead className="text-left text-muted-foreground">
                  <tr><th scope="col" className="py-2 pr-3 font-medium">Provider</th><th scope="col" className="py-2 pr-3 font-medium">Call</th><th scope="col" className="py-2 pr-3 font-medium">Status</th><th scope="col" className="py-2 text-right font-medium">Time</th></tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {d.integration_results.map((c, i) => (
                    <tr key={i}>
                      <td className="py-2 pr-3">{c.provider}</td>
                      <td className="py-2 pr-3">{c.operation}{c.attempt > 1 ? ` (attempt ${c.attempt})` : ""}</td>
                      <td className={`py-2 pr-3 ${c.status === "SUCCESS" ? "" : "text-refer font-medium"}`}>{c.status.toLowerCase()}</td>
                      <td className="py-2 text-right">{c.latency_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </div>

        <div className="space-y-6 lg:sticky lg:top-14 lg:self-start">
          {d.review ? (
            <Section title="Reviewed">
              <p className="text-sm"><span className="font-medium">{d.review.action === "APPROVE" ? "Approved" : "Declined"}</span> by {d.review.reviewer}, {dateTime(d.review.created_at)}</p>
              <p className="mt-2 text-sm">&ldquo;{d.review.notes}&rdquo;</p>
            </Section>
          ) : a.state === "REFERRED" ? (
            <ReviewForm id={a.id} onDone={load} />
          ) : null}
          <Section title="Timeline">
            <ol className="space-y-2 text-sm">
              {d.timeline.map((e, i) => (
                <li key={i}>
                  <span className="font-medium">
                    {e.event_type === "STATE_CHANGE" ? `${e.from_state ?? "start"} to ${e.to_state}` : e.event_type === "OFFER_STATUS" ? `Offer ${e.to_state?.toLowerCase()}` : `${e.event_type.replace("_", " ").toLowerCase()}: ${e.reason}`}
                  </span>
                  <span className="block text-xs text-muted-foreground">{e.actor}, {dateTime(e.created_at)}</span>
                </li>
              ))}
            </ol>
          </Section>
        </div>
      </div>
    </>
  );
}

function ReviewForm({ id, onDone }: { id: string; onDone: () => void }) {
  const { user } = useInternalAuth();
  const [action, setAction] = useState<"APPROVE" | "DECLINE">("APPROVE");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const allowed = user?.role === "ops" || user?.role === "admin";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/ops/referrals/${id}/review`, { method: "POST", token: user?.token, idempotencyKey: key.current, body: { action, notes } });
      onDone();
    } catch (err) {
      const f = fieldErrors(err);
      setError(f.notes ?? (err instanceof ApiError ? err.message : "Couldn't save the review."));
      setBusy(false);
    }
  }

  return (
    <Section title="Your review">
      {!allowed ? (
        <p className="text-sm text-muted-foreground">Sign in as ops or admin to approve or decline this application.</p>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <RadioGroup value={action} onValueChange={(v) => setAction(v as typeof action)} className="grid grid-cols-2 gap-2">
            {(["APPROVE", "DECLINE"] as const).map((v) => (
              <label key={v} className="flex h-11 cursor-pointer items-center gap-2 rounded-lg border border-input px-3 text-sm has-[[data-checked]]:border-primary has-[[data-checked]]:bg-accent">
                <RadioGroupItem value={v} />
                {v === "APPROVE" ? "Approve" : "Decline"}
              </label>
            ))}
          </RadioGroup>
          <div className="space-y-1">
            <label htmlFor="notes" className="block text-sm font-medium">Notes</label>
            <textarea id="notes" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm"
              aria-describedby="notes-hint" />
            <p id="notes-hint" className="text-xs text-muted-foreground">Required, at least 10 characters. Approving creates an offer priced under the policy version the engine used.</p>
          </div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <Button type="submit" className="h-11 w-full" disabled={busy || notes.trim().length < 10}>
            {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : null}
            {action === "APPROVE" ? "Approve application" : "Decline application"}
          </Button>
        </form>
      )}
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card px-4 py-4 sm:px-5">
      <h2 className="mb-3 font-semibold">{title}</h2>
      {children}
    </section>
  );
}
