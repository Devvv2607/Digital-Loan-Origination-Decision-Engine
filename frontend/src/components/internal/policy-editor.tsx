"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ApiError, api, fieldErrors } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useInternalAuth } from "./auth";
import { PageTitle } from "./shell";

type Params = Record<string, unknown>;

interface Rule {
  rule_id: string;
  kind: "ELIGIBILITY" | "FRAUD" | "PRICING";
  name: string;
  enabled: boolean;
  parameters: Params;
  outcome_on_fail: "DECLINE" | "REFER" | null;
  outcome_editable: boolean;
  reason_codes: string[];
  version: number;
  updated_by: string;
  change_comment: string | null;
  updated_at: string;
}

interface VersionRow {
  policy_version: number;
  rule_id: string;
  name: string;
  enabled: boolean;
  parameters: Params;
  outcome_on_fail: string | null;
  changed_by: string;
  change_comment: string | null;
  created_at: string;
}

/** How each parameter is labelled and edited. `percent` values are stored as fractions. */
type Kind = "int" | "number" | "percent" | "rate" | "text" | "choice";
const META: Record<string, Record<string, { label: string; kind: Kind; unit?: string; choices?: string[] }>> = {
  R1: { min_age_now: { label: "Minimum age today", kind: "int", unit: "years" },
        max_age_at_maturity: { label: "Maximum age when the loan ends", kind: "int", unit: "years" } },
  R2: { approve_threshold: { label: "Approve at or above", kind: "int", unit: "score" },
        refer_floor: { label: "Refer at or above (decline below)", kind: "int", unit: "score" },
        ntc_outcome: { label: "No credit history", kind: "choice", choices: ["REFER", "DECLINE"] } },
  R3: { min_monthly_income: { label: "Minimum take-home income", kind: "int", unit: "₹ a month" } },
  R4: { pass_max: { label: "Approve up to", kind: "percent", unit: "% of income" },
        refer_max: { label: "Refer up to (decline above)", kind: "percent", unit: "% of income" } },
  R5: { min_months_salaried: { label: "Salaried: months in current job", kind: "int", unit: "months" },
        min_months_self_employed: { label: "Self-employed: months in business", kind: "int", unit: "months" } },
  R6: { max_multiple_of_monthly_income: { label: "Maximum loan", kind: "number", unit: "× monthly income" },
        round_down_to: { label: "Round counter-offers down to", kind: "int", unit: "₹" } },
  F1: {},
  F2: { window_hours: { label: "Time window", kind: "int", unit: "hours" },
        max_applications: { label: "Flag above", kind: "int", unit: "applications per phone or device" } },
  F3: { name_similarity_min: { label: "Names match at or above", kind: "number", unit: "similarity (0 to 1)" } },
  F4: { income_diff_max: { label: "Flag a difference above", kind: "percent", unit: "% of declared income" } },
  PRICING: {
    fallback_rate: { label: "Rate with no score", kind: "rate", unit: "% a year" },
    processing_fee_rate: { label: "Processing fee", kind: "percent", unit: "% of loan" },
    loan_amount_min: { label: "Smallest loan", kind: "int", unit: "₹" },
    loan_amount_max: { label: "Largest loan", kind: "int", unit: "₹" },
    tenure_months_min: { label: "Shortest tenure", kind: "int", unit: "months" },
    tenure_months_max: { label: "Longest tenure", kind: "int", unit: "months" },
    offer_validity_days: { label: "Offer valid for", kind: "int", unit: "days" },
    cooling_off_days: { label: "Cooling-off period", kind: "int", unit: "days" },
    grievance_contact: { label: "Grievance contact", kind: "text" },
  },
};

const NO_PARAMS: (typeof META)[string] = {};

const GROUPS: [Rule["kind"], string, string][] = [
  ["ELIGIBILITY", "Eligibility rules", "Six rules every application is checked against."],
  ["FRAUD", "Fraud checks", "Four checks. A fraud signal refers the application; applicants never see why."],
  ["PRICING", "Pricing and product limits", "Rates by score band, fees and limits. Existing offers keep the version they were priced under."],
];

function toInput(kind: Kind, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (kind === "percent") return String(Math.round(Number(v) * 10000) / 100);
  return String(v);
}
function fromInput(kind: Kind, s: string): unknown {
  if (kind === "text" || kind === "choice") return s;
  const n = Number(s);
  if (s.trim() === "" || Number.isNaN(n)) return s; // let the server reject it with a field error
  if (kind === "percent") return Math.round(n * 100) / 10000;
  return kind === "int" ? Math.round(n) : n;
}
function label(ruleId: string, key: string): string {
  return META[ruleId]?.[key]?.label ?? (key === "rate_bands" ? "Rates by score" : key.replaceAll("_", " "));
}
function showFor(ruleId: string, key: string, v: unknown): string {
  const m = META[ruleId]?.[key];
  if (m && v !== undefined && !Array.isArray(v)) {
    const shown = m.kind === "percent" ? toInput("percent", v) : String(v);
    return m.kind === "choice" ? shown.toLowerCase() : shown;
  }
  return show(v);
}
function show(v: unknown): string {
  if (Array.isArray(v)) return v.map((b) => `${(b as { min_score: number }).min_score}+: ${(b as { annual_rate: number }).annual_rate}%`).join(", ");
  return v === undefined ? "–" : String(v);
}

export function PolicyEditor() {
  const { user, expire } = useInternalAuth();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [history, setHistory] = useState<VersionRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canEdit = user?.role === "admin";

  const load = useCallback(async () => {
    try {
      const [r, h] = await Promise.all([
        api<{ policy_version: number; rules: Rule[] }>("/admin/rules", { token: user?.token }),
        api<{ items: VersionRow[] }>("/admin/rules/versions?page_size=100", { token: user?.token }),
      ]);
      setRules(r.data.rules);
      setVersion(r.data.policy_version);
      setHistory(h.data.items);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && user) expire();
      setError(e instanceof ApiError ? e.message : "Couldn't load the policy.");
    }
  }, [user, expire]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageTitle
        title="Credit policy"
        intro="Change thresholds without a code deploy. Every save creates a new policy version; new applications use it immediately, and past decisions keep the version they were made under."
      />
      {!canEdit ? (
        <p className="mb-6 rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          You&apos;re viewing the policy read-only. {user ? "Only admins can edit it." : "Sign in as admin to edit it."}
        </p>
      ) : null}
      {error ? <p role="alert" className="mb-6 text-destructive">{error}</p> : null}
      {!rules ? (
        <p className="text-muted-foreground">Loading the policy</p>
      ) : (
        <div className="grid gap-8 lg:grid-cols-[1fr_22rem]">
          <div className="space-y-10">
            <p className="text-sm">
              Current policy: <span className="font-semibold">version {version}</span>
            </p>
            {GROUPS.map(([kind, title, intro]) => (
              <section key={kind} aria-labelledby={`g-${kind}`}>
                <h2 id={`g-${kind}`} className="text-lg font-semibold">{title}</h2>
                <p className="text-sm text-muted-foreground">{intro}</p>
                <div className="mt-3 divide-y divide-border rounded-xl border border-border bg-card">
                  {rules.filter((r) => r.kind === kind).map((r) => (
                    <RuleEditor key={`${r.rule_id}-${r.version}`} rule={r} canEdit={canEdit} token={user?.token}
                      onSaved={load} />
                  ))}
                </div>
              </section>
            ))}
          </div>
          <History rows={history} />
        </div>
      )}
    </>
  );
}

function RuleEditor({ rule, canEdit, token, onSaved }: { rule: Rule; canEdit: boolean; token?: string; onSaved: () => void }) {
  const meta = META[rule.rule_id] ?? NO_PARAMS;
  const initial = useMemo(
    () => Object.fromEntries(Object.entries(meta).map(([k, m]) => [k, toInput(m.kind, rule.parameters[k])])),
    [meta, rule.parameters],
  );
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [bands, setBands] = useState<{ min_score: string; annual_rate: string }[]>(
    ((rule.parameters.rate_bands as { min_score: number; annual_rate: number }[]) ?? []).map((b) => ({
      min_score: String(b.min_score), annual_rate: String(b.annual_rate),
    })),
  );
  const [enabled, setEnabled] = useState(rule.enabled);
  const [outcome, setOutcome] = useState(rule.outcome_on_fail);
  const [comment, setComment] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const params: Params = { ...rule.parameters };
  for (const [k, m] of Object.entries(meta)) params[k] = fromInput(m.kind, values[k] ?? "");
  if (rule.rule_id === "PRICING") {
    params.rate_bands = bands.map((b) => ({ min_score: Number(b.min_score), annual_rate: Number(b.annual_rate) }));
  }
  const dirty =
    JSON.stringify(params) !== JSON.stringify(rule.parameters) || enabled !== rule.enabled || outcome !== rule.outcome_on_fail;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    setErrors({});
    try {
      const { data } = await api<{ policy_version: number }>(`/admin/rules/${rule.rule_id}`, {
        method: "PUT",
        token,
        body: {
          enabled,
          parameters: params,
          ...(rule.outcome_editable && outcome ? { outcome_on_fail: outcome } : {}),
          change_comment: comment.trim(),
        },
      });
      setMessage(`Saved as policy version ${data.policy_version}.`);
      setComment("");
      onSaved();
    } catch (err) {
      setErrors(fieldErrors(err));
      setMessage(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  const id = rule.rule_id;
  return (
    <form onSubmit={save} className="space-y-4 px-4 py-5 sm:px-5" aria-labelledby={`r-${id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`r-${id}`} className="font-semibold">
          <span className="figures mr-2 text-muted-foreground">{id === "PRICING" ? "" : id}</span>
          {rule.name}
        </h3>
        <p className="text-xs text-muted-foreground">
          v{rule.version}, {rule.updated_by === "seed" ? "seed policy" : rule.updated_by}, {dateTime(rule.updated_at)}
        </p>
      </div>

      {id !== "PRICING" ? (
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <Checkbox checked={enabled} onCheckedChange={(v) => setEnabled(Boolean(v))} disabled={!canEdit} />
          {id.startsWith("F") ? "Check is on" : "Rule is on"}
        </label>
      ) : null}

      {id === "R2" && rule.parameters.calibration ? (
        <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          Seeded from the credit-risk project&apos;s 88.2% reference approval rate with a 5% refer band. Illustrative
          only; it does not establish equivalent risk.
        </p>
      ) : null}

      {Object.keys(meta).length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(meta).map(([k, m]) => {
            const fid = `${id}-${k}`;
            const err = errors[k];
            return (
              <div key={k} className="space-y-1">
                <label htmlFor={fid} className="block text-sm font-medium">{m.label}</label>
                {m.kind === "choice" ? (
                  <select id={fid} value={values[k]} disabled={!canEdit}
                    onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                    className="h-11 w-full rounded-lg border border-input bg-card px-3 disabled:opacity-70">
                    {m.choices!.map((c) => <option key={c} value={c}>{c === "REFER" ? "Refer" : "Decline"}</option>)}
                  </select>
                ) : (
                  <div className="flex items-center gap-2">
                    <Input id={fid} value={values[k]} disabled={!canEdit}
                      inputMode={m.kind === "text" ? "text" : "decimal"}
                      onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                      aria-invalid={err ? true : undefined}
                      aria-describedby={err ? `${fid}-err` : undefined}
                      className={cn("h-11 disabled:opacity-70", m.kind !== "text" && "figures max-w-36")} />
                    {m.unit ? <span className="text-sm text-muted-foreground">{m.unit}</span> : null}
                  </div>
                )}
                {err ? <p id={`${fid}-err`} className="text-xs text-destructive">{err}</p> : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Blocks a PAN that another application in progress already uses. No thresholds; it can only be turned on or off.
        </p>
      )}

      {id === "PRICING" ? (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Interest rate by bureau score</legend>
          {bands.map((b, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Score</span>
              <Input aria-label={`Band ${i + 1} minimum score`} value={b.min_score} disabled={!canEdit}
                onChange={(e) => setBands((bs) => bs.map((x, j) => (j === i ? { ...x, min_score: e.target.value } : x)))}
                className="figures h-11 w-24 disabled:opacity-70" />
              <span className="text-muted-foreground">and above</span>
              <Input aria-label={`Band ${i + 1} annual rate`} value={b.annual_rate} disabled={!canEdit}
                onChange={(e) => setBands((bs) => bs.map((x, j) => (j === i ? { ...x, annual_rate: e.target.value } : x)))}
                className="figures h-11 w-24 disabled:opacity-70" />
              <span className="text-muted-foreground">% a year</span>
            </div>
          ))}
          {errors.rate_bands ? <p className="text-xs text-destructive">{errors.rate_bands}</p> : null}
        </fieldset>
      ) : null}

      {rule.outcome_editable ? (
        <div className="space-y-1">
          <label htmlFor={`${id}-outcome`} className="block text-sm font-medium">If the rule fails</label>
          <select id={`${id}-outcome`} value={outcome ?? ""} disabled={!canEdit}
            onChange={(e) => setOutcome(e.target.value as Rule["outcome_on_fail"])}
            className="h-11 w-full max-w-56 rounded-lg border border-input bg-card px-3 disabled:opacity-70">
            <option value="DECLINE">Decline</option>
            <option value="REFER">Refer to an analyst</option>
          </select>
        </div>
      ) : null}

      {canEdit && dirty ? (
        <div className="flex flex-col gap-2 rounded-lg bg-muted p-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <label htmlFor={`${id}-comment`} className="block text-sm font-medium">Why are you changing this?</label>
            <Input id={`${id}-comment`} value={comment} onChange={(e) => setComment(e.target.value)} className="h-11"
              placeholder="Recorded in the version history" />
          </div>
          <Button type="submit" className="h-11 px-4" disabled={busy || comment.trim().length < 3}>
            {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : null}
            Save new version
          </Button>
        </div>
      ) : null}
      {message ? <p role="status" className="text-sm">{message}</p> : null}
    </form>
  );
}

function History({ rows }: { rows: VersionRow[] }) {
  // Each change is diffed against the previous version of the same rule.
  const entries = rows
    .map((row, i) => {
      const prev = rows.slice(i + 1).find((r) => r.rule_id === row.rule_id);
      if (!prev) return { row, changes: null };
      const keys = new Set([...Object.keys(row.parameters), ...Object.keys(prev.parameters)]);
      const changes: [string, string, string][] = [];
      for (const k of keys) {
        if (k === "calibration") continue;
        if (JSON.stringify(row.parameters[k]) !== JSON.stringify(prev.parameters[k]))
          changes.push([label(row.rule_id, k), showFor(row.rule_id, k, prev.parameters[k]),
            `${showFor(row.rule_id, k, row.parameters[k])}${META[row.rule_id]?.[k]?.unit ? ` ${META[row.rule_id][k].unit}` : ""}`]);
      }
      if (row.enabled !== prev.enabled) changes.push(["Status", prev.enabled ? "on" : "off", row.enabled ? "on" : "off"]);
      if (row.outcome_on_fail !== prev.outcome_on_fail)
        changes.push(["If it fails", String(prev.outcome_on_fail).toLowerCase(), String(row.outcome_on_fail).toLowerCase()]);
      return { row, changes };
    })
    .filter((e) => e.changes !== null);

  return (
    <aside aria-labelledby="history-title" className="lg:sticky lg:top-14 lg:self-start">
      <h2 id="history-title" className="text-lg font-semibold">Version history</h2>
      <p className="text-sm text-muted-foreground">Every change, newest first. Version 1 is the seed policy.</p>
      {entries.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-input px-4 py-3 text-sm text-muted-foreground">
          No changes since the seed policy.
        </p>
      ) : (
        <ol className="mt-3 space-y-3">
          {entries.map(({ row, changes }) => (
            <li key={`${row.rule_id}-${row.policy_version}`} className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
              <p className="font-medium">
                Version {row.policy_version}: {row.name}
              </p>
              <p className="text-xs text-muted-foreground">
                {row.changed_by}, {dateTime(row.created_at)}
              </p>
              {row.change_comment ? <p className="mt-1">&ldquo;{row.change_comment}&rdquo;</p> : null}
              <ul className="figures mt-2 space-y-0.5 text-xs">
                {changes!.map(([k, a, b]) => (
                  <li key={k}>
                    <span className="text-muted-foreground">{k}: </span>
                    <del className="text-decline decoration-decline/60">{a}</del> <span aria-hidden>to</span>{" "}
                    <ins className="text-approve no-underline">{b}</ins>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
