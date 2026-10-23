"use client";

import { useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ApiError, api, fieldErrors, newIdempotencyKey } from "@/lib/api";
import { inr } from "@/lib/format";
import type { Details } from "@/lib/types";

import type { FlowContext } from "../flow";
import { ActionButton, ErrorNotice, Field, StepShell, describe, inputClass, selectClass } from "../ui";

export const PURPOSES: [string, string][] = [
  ["HOME_RENOVATION", "Home renovation"],
  ["MEDICAL", "Medical expenses"],
  ["EDUCATION", "Education"],
  ["TRAVEL", "Travel"],
  ["WEDDING", "Wedding"],
  ["DEBT_CONSOLIDATION", "Paying off other loans"],
  ["OTHER", "Something else"],
];
const TENURES = [12, 24, 36, 48, 60];

type Form = Record<keyof Details, string>;

function toForm(d: Partial<Details> | undefined): Form {
  const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  return {
    full_name: s(d?.full_name),
    date_of_birth: s(d?.date_of_birth),
    employment_type: s(d?.employment_type) || "SALARIED",
    employer_name: s(d?.employer_name),
    months_in_current_job: s(d?.months_in_current_job),
    declared_monthly_income: s(d?.declared_monthly_income),
    loan_amount: s(d?.loan_amount),
    tenure_months: s(d?.tenure_months) || "36",
    purpose: s(d?.purpose) || "HOME_RENOVATION",
  };
}

const NUMERIC: (keyof Details)[] = ["months_in_current_job", "declared_monthly_income", "loan_amount", "tenure_months"];

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (f.full_name.trim().length < 2) e.full_name = "Enter your full name as it appears on your PAN.";
  if (!f.date_of_birth) e.date_of_birth = "Enter your date of birth.";
  if (f.employer_name.trim().length < 2)
    e.employer_name = f.employment_type === "SALARIED" ? "Enter your employer's name." : "Enter your business name.";
  for (const k of NUMERIC) if (f[k] === "" || Number.isNaN(Number(f[k]))) e[k] = "Enter a number.";
  return e;
}

export function DetailsStep({ ctx }: { ctx: FlowContext }) {
  const saved = ctx.app?.details;
  const hasSaved = saved && Object.values(saved).some((v) => v !== null);
  const [form, setForm] = useState<Form>(toForm(hasSaved ? saved : ctx.session.persona?.details));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useRef(newIdempotencyKey());

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const salaried = form.employment_type === "SALARIED";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local = validate(form);
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    const body = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, NUMERIC.includes(k as keyof Details) ? Number(v) : v.trim()]),
    );
    try {
      await api(`/applications/${ctx.session.applicationId}`, { method: "PATCH", token: ctx.session.token, body });
      await api(`/applications/${ctx.session.applicationId}/submit`, {
        method: "POST",
        token: ctx.session.token,
        idempotencyKey: submitKey.current,
      });
      await ctx.refresh();
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(err instanceof ApiError ? err.message : "Couldn't save your details.");
      setBusy(false);
    }
  }

  const amount = Number(form.loan_amount);
  return (
    <StepShell title="About you and your loan" intro="Use the same name as on your PAN card.">
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        <Field id="full_name" label="Full name" error={errors.full_name}>
          <Input id="full_name" autoComplete="name" value={form.full_name} onChange={set("full_name")}
            className={inputClass} {...describe("full_name", errors.full_name)} />
        </Field>
        <Field id="date_of_birth" label="Date of birth" error={errors.date_of_birth}>
          <Input id="date_of_birth" type="date" autoComplete="bday" value={form.date_of_birth}
            onChange={set("date_of_birth")} className={inputClass} {...describe("date_of_birth", errors.date_of_birth)} />
        </Field>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">How do you earn?</legend>
          <RadioGroup
            value={form.employment_type}
            onValueChange={(v) => setForm((f) => ({ ...f, employment_type: String(v) }))}
            className="grid grid-cols-2 gap-2"
          >
            {[["SALARIED", "Salaried"], ["SELF_EMPLOYED", "Self-employed"]].map(([value, label]) => (
              <label key={value} className="flex h-11 cursor-pointer items-center gap-2.5 rounded-lg border border-input bg-card px-3 has-[[data-checked]]:border-primary has-[[data-checked]]:bg-accent">
                <RadioGroupItem value={value} />
                <span>{label}</span>
              </label>
            ))}
          </RadioGroup>
        </fieldset>

        <Field id="employer_name" label={salaried ? "Employer" : "Business name"} error={errors.employer_name}>
          <Input id="employer_name" autoComplete="organization" value={form.employer_name}
            onChange={set("employer_name")} className={inputClass} {...describe("employer_name", errors.employer_name)} />
        </Field>
        <Field id="months_in_current_job" label={salaried ? "Months in your current job" : "Months running this business"}
          error={errors.months_in_current_job}>
          <Input id="months_in_current_job" inputMode="numeric" value={form.months_in_current_job}
            onChange={set("months_in_current_job")} className={inputClass}
            {...describe("months_in_current_job", errors.months_in_current_job)} />
        </Field>
        <Field id="declared_monthly_income" label="Take-home income per month (₹)" hint="After tax and deductions"
          error={errors.declared_monthly_income}>
          <Input id="declared_monthly_income" inputMode="numeric" value={form.declared_monthly_income}
            onChange={set("declared_monthly_income")} className={`${inputClass} figures`}
            {...describe("declared_monthly_income", errors.declared_monthly_income, "After tax and deductions")} />
        </Field>

        <div className="border-t border-border pt-5" />

        <Field id="loan_amount" label="How much do you want to borrow? (₹)"
          hint={amount > 0 ? `${inr(amount)}. Between ₹50,000 and ₹25,00,000.` : "Between ₹50,000 and ₹25,00,000."}
          error={errors.loan_amount}>
          <Input id="loan_amount" inputMode="numeric" value={form.loan_amount} onChange={set("loan_amount")}
            className={`${inputClass} figures`} {...describe("loan_amount", errors.loan_amount, "amount")} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field id="tenure_months" label="Repay over" error={errors.tenure_months}>
            <select id="tenure_months" value={form.tenure_months} onChange={set("tenure_months")} className={selectClass}
              {...describe("tenure_months", errors.tenure_months)}>
              {TENURES.map((t) => (
                <option key={t} value={t}>{t} months</option>
              ))}
            </select>
          </Field>
          <Field id="purpose" label="What is it for?" error={errors.purpose}>
            <select id="purpose" value={form.purpose} onChange={set("purpose")} className={selectClass}
              {...describe("purpose", errors.purpose)}>
              {PURPOSES.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
        </div>

        <ErrorNotice message={error} />
        <ActionButton type="submit" busy={busy} busyLabel="Saving your details">
          Save and continue
        </ActionButton>
      </form>
    </StepShell>
  );
}
