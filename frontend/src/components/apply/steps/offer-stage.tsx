"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { date, inr, months, pct } from "@/lib/format";
import type { Offer, OfferActionResult } from "@/lib/types";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, Notice, StepShell, describe, inputClass } from "../ui";

/** Loads the offer and shows the right sub-step: KFS -> e-sign -> disbursal -> done. */
export function OfferStage({ ctx }: { ctx: FlowContext }) {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = `/applications/${ctx.session.applicationId}`;

  const load = useCallback(async () => {
    try {
      const { data } = await api<Offer>(`${path}/offer`, { token: ctx.session.token });
      setOffer(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load your offer.");
    }
  }, [path, ctx.session.token]);

  useEffect(() => {
    void load();
  }, [load]);

  const { setOfferPhase } = ctx;
  useEffect(() => {
    if (!offer) return;
    setOfferPhase(
      offer.application_state === "DISBURSED" ? "done" : offer.status === "GENERATED" ? "kfs" : "sign",
    );
  }, [offer, setOfferPhase]);

  if (error) return <ErrorNotice message={error} />;
  if (!offer) return <p className="text-muted-foreground">Loading your offer</p>;

  const onExpired = () => ctx.refresh();
  if (offer.application_state === "DISBURSED") return <Disbursed offer={offer} ctx={ctx} />;
  if (offer.status === "ESIGNED") return <Disburse offer={offer} ctx={ctx} onDone={load} />;
  if (offer.status === "ACCEPTED") return <Esign offer={offer} ctx={ctx} onDone={load} onExpired={onExpired} />;
  return <Kfs offer={offer} ctx={ctx} onDone={load} onExpired={onExpired} />;
}

// ---------------------------------------------------------------- KFS

function Kfs({ offer, ctx, onDone, onExpired }: { offer: Offer; ctx: FlowContext; onDone: () => void; onExpired: () => void }) {
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());

  async function accept() {
    setError(null);
    setBusy(true);
    try {
      await api<OfferActionResult>(`/applications/${ctx.session.applicationId}/offer/accept`, {
        method: "POST",
        token: ctx.session.token,
        idempotencyKey: key.current,
        body: { kfs_acknowledged: read },
      });
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.code === "OFFER_EXPIRED") return onExpired();
      setError(err instanceof ApiError ? err.message : "Couldn't accept the offer.");
      setBusy(false);
    }
  }

  const rows: [string, string, boolean?][] = [
    ["Loan amount", inr(offer.loan_amount)],
    ["Processing fee", inr(offer.total_fees)],
    ["Amount paid to you", inr(offer.net_disbursal), true],
    ["Repayment period", months(offer.tenure_months)],
    ["Interest rate", `${pct(offer.interest_rate)} a year (reducing balance)`],
    ["Annual percentage rate (APR)", `${pct(offer.apr)} a year, including the fee`, true],
    ["Monthly instalment (EMI)", inr(offer.emi), true],
    ["Total interest", inr(offer.total_interest)],
    ["Total fees", inr(offer.total_fees)],
    ["Total you repay", inr(offer.total_repayment), true],
  ];

  return (
    <StepShell title="Your loan offer" intro="Read the key facts below. Nothing is final until you accept and sign.">
      {offer.amount_capped ? (
        <Notice tone="refer" title={`We can offer ${inr(offer.loan_amount)}`}>
          You asked for {inr(offer.requested_amount)}. Based on your income, the most we can lend is{" "}
          {inr(offer.loan_amount)}, and the figures below are for that amount.
        </Notice>
      ) : null}

      <article aria-labelledby="kfs-title" className="rounded-xl border border-border bg-card font-serif">
        <header className="border-b border-border px-5 py-4">
          <h2 id="kfs-title" className="text-xl font-semibold">Key Fact Statement</h2>
          <p className="mt-1 font-sans text-xs text-muted-foreground">{offer.disclaimer}</p>
        </header>
        <dl className="divide-y divide-border px-5">
          {rows.map(([k, v, strong]) => (
            <div key={k} className="grid grid-cols-[1fr_auto] gap-4 py-2.5 text-[1rem]">
              <dt className={strong ? "font-semibold" : undefined}>{k}</dt>
              <dd className={`figures text-right ${strong ? "font-semibold" : ""}`}>{v}</dd>
            </div>
          ))}
        </dl>

        <Collapsible className="border-t border-border">
          <CollapsibleTrigger className="group flex w-full items-center justify-between px-5 py-3 text-left font-sans text-sm font-medium text-primary">
            Repayment schedule ({offer.schedule.length} instalments)
            <ChevronDown className="size-4 transition-transform group-data-[panel-open]:rotate-180" aria-hidden />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="max-h-72 overflow-auto px-5 pb-4">
              <table className="figures w-full font-sans text-sm">
                <caption className="sr-only">Monthly repayment schedule</caption>
                <thead className="sticky top-0 bg-card text-muted-foreground">
                  <tr>
                    <th scope="col" className="py-1.5 text-left font-medium">Month</th>
                    <th scope="col" className="py-1.5 text-right font-medium">EMI</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Interest</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Principal</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {offer.schedule.map((r) => (
                    <tr key={r.month}>
                      <td className="py-1.5">{r.month}</td>
                      <td className="py-1.5 text-right">{inr(r.emi)}</td>
                      <td className="py-1.5 text-right">{inr(r.interest)}</td>
                      <td className="py-1.5 text-right">{inr(r.principal)}</td>
                      <td className="py-1.5 text-right">{inr(r.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <div className="space-y-3 border-t border-border px-5 py-4 text-[0.95rem]">
          <p>
            <span className="font-semibold">Cooling-off period. </span>
            You can exit this loan within {offer.cooling_off_days} days of receiving the money by repaying the
            principal and interest for the days you had it.
          </p>
          <p>
            <span className="font-semibold">Complaints. </span>
            Write to {offer.grievance_contact} (placeholder address for this demo).
          </p>
          <div>
            <p className="font-semibold">How these figures are worked out</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 font-sans text-sm text-muted-foreground">
              {offer.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
          <p className="font-sans text-xs text-muted-foreground">
            Offer valid until {date(offer.expires_at)}. Priced under credit policy version {offer.policy_version}.
          </p>
        </div>
      </article>

      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-input bg-card px-4 py-3">
        <Checkbox checked={read} onCheckedChange={(v) => setRead(Boolean(v))} className="mt-0.5" />
        <span className="text-[0.95rem]">I have read the Key Fact Statement</span>
      </label>
      <ErrorNotice message={error} />
      <ActionButton disabled={!read} busy={busy} busyLabel="Accepting your offer" onClick={accept}>
        Accept offer
      </ActionButton>
      {!read ? <p className="text-sm text-muted-foreground">Tick the box above to accept.</p> : null}
    </StepShell>
  );
}

// ---------------------------------------------------------------- e-sign

function Esign({ offer, ctx, onDone, onExpired }: { offer: Offer; ctx: FlowContext; onDone: () => void; onExpired: () => void }) {
  const [name, setName] = useState(ctx.app?.details.full_name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());

  async function sign(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api(`/applications/${ctx.session.applicationId}/offer/esign`, {
        method: "POST",
        token: ctx.session.token,
        idempotencyKey: key.current,
        body: { signature_name: name.trim() },
      });
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.code === "OFFER_EXPIRED") return onExpired();
      setError(err instanceof ApiError ? err.message : "Couldn't sign the agreement.");
      setBusy(false);
    }
  }

  return (
    <StepShell
      title="Sign your loan agreement"
      intro={`You've accepted ${inr(offer.loan_amount)} over ${months(offer.tenure_months)} at an EMI of ${inr(offer.emi)}. Typing your name below is a simulated e-signature.`}
    >
      <form onSubmit={sign} className="space-y-4" noValidate>
        <Field id="signature" label="Type your full name to sign">
          <Input id="signature" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name"
            className={`${inputClass} font-serif italic`} {...describe("signature")} />
        </Field>
        <ErrorNotice message={error} />
        <ActionButton type="submit" disabled={name.trim().length < 2} busy={busy} busyLabel="Signing (simulated)">
          Sign agreement
        </ActionButton>
      </form>
    </StepShell>
  );
}

// ---------------------------------------------------------------- disbursal

function Disburse({ offer, ctx, onDone }: { offer: Offer; ctx: FlowContext; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());

  async function disburse() {
    setError(null);
    setBusy(true);
    try {
      await api(`/applications/${ctx.session.applicationId}/disburse`, {
        method: "POST",
        token: ctx.session.token,
        idempotencyKey: key.current,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send the money. Please try again.");
      setBusy(false);
    }
  }

  return (
    <StepShell title="Agreement signed" intro={`Signature reference ${offer.esign_reference}.`}>
      <p className="text-[0.95rem]">
        The last step pays {inr(offer.net_disbursal)} into your bank account. In this demo the payment is simulated.
      </p>
      <ErrorNotice message={error} />
      <ActionButton busy={busy} busyLabel="Sending the money (simulated)" onClick={disburse}>
        Receive {inr(offer.net_disbursal)}
      </ActionButton>
    </StepShell>
  );
}

function Disbursed({ offer, ctx }: { offer: Offer; ctx: FlowContext }) {
  const firstEmi = offer.disbursed_at ? new Date(offer.disbursed_at) : new Date();
  firstEmi.setMonth(firstEmi.getMonth() + 1);
  return (
    <StepShell title={`${inr(offer.net_disbursal)} is on its way`}>
      <Notice tone="approve">
        Your loan has been paid out (simulated). Reference {offer.disbursal_reference}.
      </Notice>
      <dl className="divide-y divide-border rounded-lg border border-border bg-card text-[0.95rem]">
        {[
          ["First EMI", `${inr(offer.emi)} on ${date(firstEmi.toISOString())}`],
          ["Number of EMIs", String(offer.tenure_months)],
          ["Cooling-off", `You can exit within ${offer.cooling_off_days} days without a penalty`],
        ].map(([k, v]) => (
          <div key={k} className="grid grid-cols-[8rem_1fr] gap-3 px-4 py-3">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="figures">{v}</dd>
          </div>
        ))}
      </dl>
      <ActionButton variant="outline" onClick={ctx.startOver}>
        Start a new application
      </ActionButton>
    </StepShell>
  );
}
