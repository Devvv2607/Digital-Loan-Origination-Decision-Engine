"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Hourglass, Info, X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";

import { useInternalAuth } from "./auth";
import { PageTitle } from "./shell";

/* Chart colours. The median/P90 pair passed the dataviz validator (lightness band, chroma,
   colour-blind separation, contrast vs surface). Outcome colours are status colours and are
   always paired with a text label and an icon, never used alone. */
const C = {
  series: "#008C85",
  p90: "#D4732A",
  ink: "#14213D",
  muted: "#4F5D75",
  grid: "#E3E9EF",
  approve: "#1E7B4F",
  refer: "#A86A12",
  decline: "#A83838",
};

interface Funnel {
  stages: { stage: string; count: number; drop_off_from_previous?: number | null }[];
  conversion_application_to_disbursal: number | null;
  decision_mix: Record<"APPROVED" | "REFERRED" | "DECLINED", number>;
  analyst_decisions: Record<"APPROVED" | "DECLINED", number>;
  engine_decisions: number;
  instant_decision_rate: number | null;
  referral_rate: number | null;
  fraud_flag_rate: number | null;
  fraud_flags: number;
  pan_attempts: number;
  top_reason_codes: { code: string; count: number }[];
  definitions: Record<string, string>;
}
interface Tat {
  states: { state: string; n_completed: number; median: number | null; p90: number | null; currently_in_state: number }[];
  definition: string;
  simulated_timings: boolean;
  seeded_applications: number;
  applications: number;
}

const STAGE_LABEL: Record<string, string> = {
  CREATED: "Started", SUBMITTED: "Submitted details", ASSESSED: "Got a decision", APPROVED: "Approved", DISBURSED: "Disbursed",
};
const STATE_LABEL: Record<string, string> = {
  DRAFT: "Filling in details", KYC_PENDING: "PAN, e-KYC, bank data", UNDER_ASSESSMENT: "Decision engine",
  REFERRED: "Waiting for an analyst", APPROVED: "Offer to disbursal",
};

const pct = (v: number | null) => (v === null ? "No data" : `${(v * 100).toFixed(1)}%`);

export function duration(seconds: number | null): string {
  if (seconds === null) return "–";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} days`;
}

export function MetricsDashboard() {
  const { user } = useInternalAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [range, setRange] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [tat, setTat] = useState<Tat | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = new URLSearchParams({ ...(range.from ? { from: range.from } : {}), ...(range.to ? { to: range.to } : {}) });
    Promise.all([
      api<Funnel>(`/metrics/funnel?${q}`, { token: user?.token }),
      api<Tat>(`/metrics/tat?${q}`, { token: user?.token }),
    ])
      .then(([f, t]) => { setFunnel(f.data); setTat(t.data); setError(null); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load metrics."));
  }, [range, user?.token]);

  const created = funnel?.stages[0]?.count ?? 0;
  return (
    <>
      <PageTitle
        title="Metrics"
        intro="Where applicants drop off, how long each stage takes, and how decisions split. Everything is computed from the application event log; in this demo it reflects synthetic traffic only."
      />
      <form
        className="mb-6 flex flex-wrap items-end gap-3"
        onSubmit={(e) => { e.preventDefault(); setRange({ from, to }); }}
        aria-label="Date range"
      >
        <div className="space-y-1">
          <label htmlFor="from" className="block text-sm font-medium">From</label>
          <Input id="from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 w-44" />
        </div>
        <div className="space-y-1">
          <label htmlFor="to" className="block text-sm font-medium">To</label>
          <Input id="to" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 w-44" />
        </div>
        <Button type="submit" className="h-11 px-4">Apply</Button>
        {range.from || range.to ? (
          <Button type="button" variant="ghost" className="h-11 px-3" onClick={() => { setFrom(""); setTo(""); setRange({ from: "", to: "" }); }}>
            All time
          </Button>
        ) : null}
      </form>

      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {!funnel || !tat ? (
        <p className="text-muted-foreground">Loading metrics</p>
      ) : created === 0 ? (
        <div className="rounded-xl border border-dashed border-input bg-card px-5 py-10 text-center">
          <p className="font-medium">No applications in this period</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Run a <Link href="/#personas" className="text-primary underline">demo applicant</Link> to see the funnel fill in.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Started to disbursed" value={pct(funnel.conversion_application_to_disbursal)}
              context={`${funnel.stages[4].count} of ${created} applications`} definition={funnel.definitions.conversion_application_to_disbursal} />
            <Stat label="Instant decisions" value={pct(funnel.instant_decision_rate)}
              context={`of ${funnel.engine_decisions} engine decisions`} definition={funnel.definitions.instant_decision_rate} />
            <Stat label="Referred to an analyst" value={pct(funnel.referral_rate)}
              context={`of ${funnel.engine_decisions} engine decisions`} definition={funnel.definitions.referral_rate} />
            <Stat label="Fraud flags" value={pct(funnel.fraud_flag_rate)}
              context={`${funnel.fraud_flags} of ${funnel.pan_attempts} that reached PAN`} definition={funnel.definitions.fraud_flag_rate} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <FunnelChart funnel={funnel} />
            <DecisionMix funnel={funnel} />
          </div>
          <TatChart tat={tat} />
          <ReasonsChart funnel={funnel} />
        </div>
      )}
    </>
  );
}

function Stat({ label, value, context, definition }: { label: string; value: string; context: string; definition: string }) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-4">
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        {label}
        <span title={definition} aria-label={`How it's measured: ${definition}`} role="img">
          <Info className="size-3.5" aria-hidden />
        </span>
      </p>
      <p className="figures mt-1 text-2xl font-semibold">{value}</p>
      <p className="text-xs text-muted-foreground">{context}</p>
    </div>
  );
}

function Panel({ title, badge, intro, children, table }: {
  title: string; badge?: string; intro: string; children: React.ReactNode; table: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-card px-4 py-4 sm:px-5" aria-label={title}>
      <h2 className="flex flex-wrap items-center gap-2 font-semibold">
        {title}
        {badge ? (
          <span className="rounded-full border border-refer/40 bg-refer-soft px-2.5 py-0.5 text-xs font-medium text-refer">{badge}</span>
        ) : null}
      </h2>
      <p className="text-sm text-muted-foreground">{intro}</p>
      <div className="mt-4">{children}</div>
      <details className="mt-3 text-sm">
        <summary className="flex min-h-11 cursor-pointer items-center text-primary">Show as a table</summary>
        <div className="overflow-x-auto">{table}</div>
      </details>
    </section>
  );
}

const axis = { fontSize: 12, fill: C.muted };
const tooltipStyle = { borderRadius: 8, border: `1px solid ${C.grid}`, fontSize: 13, color: C.ink };

function FunnelChart({ funnel }: { funnel: Funnel }) {
  const data = funnel.stages.map((s) => ({
    name: STAGE_LABEL[s.stage],
    count: s.count,
    label: s.drop_off_from_previous ? `${s.count} (−${Math.round(s.drop_off_from_previous * 100)}%)` : `${s.count}`,
  }));
  return (
    <Panel title="Funnel" intro="Applications reaching each stage; the figure in brackets is the drop-off from the stage before."
      table={
        <table className="figures mt-2 w-full text-left">
          <thead><tr><th scope="col" className="py-1.5">Stage</th><th scope="col" className="py-1.5 text-right">Applications</th><th scope="col" className="py-1.5 text-right">Drop-off</th></tr></thead>
          <tbody>{funnel.stages.map((s) => (
            <tr key={s.stage} className="border-t border-border"><td className="py-1.5">{STAGE_LABEL[s.stage]}</td><td className="py-1.5 text-right">{s.count}</td>
              <td className="py-1.5 text-right">{s.drop_off_from_previous === undefined || s.drop_off_from_previous === null ? "–" : `${(s.drop_off_from_previous * 100).toFixed(1)}%`}</td></tr>
          ))}</tbody>
        </table>
      }>
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 72 }} barCategoryGap={6}>
            <CartesianGrid horizontal={false} stroke={C.grid} />
            <XAxis type="number" tick={axis} axisLine={false} tickLine={false} allowDecimals={false} />
            <YAxis type="category" dataKey="name" width={118} tick={axis} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "#EEF3F7" }} contentStyle={tooltipStyle} formatter={(v) => [v, "Applications"]} />
            <Bar dataKey="count" fill={C.series} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="label" position="right" style={{ fontSize: 12, fill: C.ink }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

const OUTCOMES = [
  { key: "APPROVED", label: "Approved", color: C.approve, Icon: Check },
  { key: "REFERRED", label: "Referred", color: C.refer, Icon: Hourglass },
  { key: "DECLINED", label: "Declined", color: C.decline, Icon: X },
] as const;

function DecisionMix({ funnel }: { funnel: Funnel }) {
  const total = funnel.engine_decisions || 1;
  const data = OUTCOMES.map((o) => ({
    name: o.label, value: funnel.decision_mix[o.key], color: o.color,
    label: `${funnel.decision_mix[o.key]} (${Math.round((funnel.decision_mix[o.key] / total) * 100)}%)`,
  }));
  const analyst = funnel.analyst_decisions;
  return (
    <Panel title="Decision mix" intro="Engine decisions by outcome. Referred applications are then approved or declined by an analyst."
      table={
        <table className="figures mt-2 w-full text-left">
          <thead><tr><th scope="col" className="py-1.5">Outcome</th><th scope="col" className="py-1.5 text-right">Engine</th><th scope="col" className="py-1.5 text-right">Share</th></tr></thead>
          <tbody>{data.map((d) => (
            <tr key={d.name} className="border-t border-border"><td className="py-1.5">{d.name}</td><td className="py-1.5 text-right">{d.value}</td><td className="py-1.5 text-right">{((d.value / total) * 100).toFixed(1)}%</td></tr>
          ))}</tbody>
        </table>
      }>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Legend">
        {OUTCOMES.map(({ key, label, color, Icon }) => (
          <li key={key} className="inline-flex items-center gap-1.5">
            <Icon className="size-4" style={{ color }} aria-hidden />
            {label}
          </li>
        ))}
      </ul>
      <div className="h-44">
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 72 }} barCategoryGap={8}>
            <CartesianGrid horizontal={false} stroke={C.grid} />
            <XAxis type="number" tick={axis} axisLine={false} tickLine={false} allowDecimals={false} />
            <YAxis type="category" dataKey="name" width={80} tick={axis} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "#EEF3F7" }} contentStyle={tooltipStyle} formatter={(v) => [v, "Decisions"]} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} minPointSize={2} isAnimationActive={false}>
              {data.map((d) => <Cell key={d.name} fill={d.color} />)}
              <LabelList dataKey="label" position="right" style={{ fontSize: 12, fill: C.ink }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-sm text-muted-foreground">
        Analysts have since approved {analyst.APPROVED} and declined {analyst.DECLINED} referrals.
      </p>
    </Panel>
  );
}

function TatChart({ tat }: { tat: Tat }) {
  const rows = tat.states.filter((s) => s.n_completed > 0);
  const data = rows.map((s) => ({ name: STATE_LABEL[s.state], median: s.median ?? 0, p90: s.p90 ?? 0 }));
  return (
    <Panel title="Time in each stage"
      badge={tat.simulated_timings ? "Simulated timings" : undefined}
      intro={`${tat.definition} Shown for stages at least one application has finished.${tat.simulated_timings
        ? ` ${tat.seeded_applications} of ${tat.applications} applications are seeded demo data whose stage durations are simulated from assumed distributions (for example e-KYC in minutes, offer acceptance in hours), not measured.`
        : ""}`}
      table={
        <table className="figures mt-2 w-full min-w-[30rem] text-left">
          <thead><tr><th scope="col" className="py-1.5">Stage</th><th scope="col" className="py-1.5 text-right">Median</th><th scope="col" className="py-1.5 text-right">90th percentile</th><th scope="col" className="py-1.5 text-right">Finished</th><th scope="col" className="py-1.5 text-right">Still there</th></tr></thead>
          <tbody>{tat.states.map((s) => (
            <tr key={s.state} className="border-t border-border"><td className="py-1.5">{STATE_LABEL[s.state]}</td><td className="py-1.5 text-right">{duration(s.median)}</td><td className="py-1.5 text-right">{duration(s.p90)}</td><td className="py-1.5 text-right">{s.n_completed}</td><td className="py-1.5 text-right">{s.currently_in_state}</td></tr>
          ))}</tbody>
        </table>
      }>
      {data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No application has finished a stage yet.</p>
      ) : (
        <div style={{ height: 70 + data.length * 56 }}>
          <ResponsiveContainer>
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 72 }} barCategoryGap={10} barGap={2}>
              <CartesianGrid horizontal={false} stroke={C.grid} />
              <XAxis type="number" tick={axis} axisLine={false} tickLine={false} tickFormatter={(v) => duration(Number(v))} />
              <YAxis type="category" dataKey="name" width={150} tick={axis} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "#EEF3F7" }} contentStyle={tooltipStyle}
                formatter={(v, n) => [duration(Number(v)), n === "median" ? "Median" : "90th percentile"]} />
              <Legend verticalAlign="top" align="left" height={28} iconType="square"
                formatter={(v) => <span style={{ color: C.ink, fontSize: 13 }}>{v === "median" ? "Median" : "90th percentile"}</span>} />
              <Bar dataKey="median" fill={C.series} radius={[0, 4, 4, 0]} minPointSize={2} isAnimationActive={false}>
                <LabelList dataKey="median" position="right" formatter={(v) => duration(Number(v))} style={{ fontSize: 12, fill: C.ink }} />
              </Bar>
              <Bar dataKey="p90" fill={C.p90} radius={[0, 4, 4, 0]} minPointSize={2} isAnimationActive={false}>
                <LabelList dataKey="p90" position="right" formatter={(v) => duration(Number(v))} style={{ fontSize: 12, fill: C.ink }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  );
}

function ReasonsChart({ funnel }: { funnel: Funnel }) {
  const data = funnel.top_reason_codes;
  return (
    <Panel title="Top reason codes" intro={funnel.definitions.top_reason_codes}
      table={
        <table className="figures mt-2 w-full text-left">
          <thead><tr><th scope="col" className="py-1.5">Code</th><th scope="col" className="py-1.5 text-right">Decisions</th></tr></thead>
          <tbody>{data.map((r) => (<tr key={r.code} className="border-t border-border"><td className="py-1.5">{r.code}</td><td className="py-1.5 text-right">{r.count}</td></tr>))}</tbody>
        </table>
      }>
      {data.length === 0 ? (
        <p className="text-sm text-muted-foreground">Every decision so far was a clean approval.</p>
      ) : (
        <div style={{ height: 40 + data.length * 34 }}>
          <ResponsiveContainer>
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 40 }} barCategoryGap={6}>
              <CartesianGrid horizontal={false} stroke={C.grid} />
              <XAxis type="number" tick={axis} axisLine={false} tickLine={false} allowDecimals={false} />
              <YAxis type="category" dataKey="code" width={190} tick={axis} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "#EEF3F7" }} contentStyle={tooltipStyle} formatter={(v) => [v, "Decisions"]} />
              <Bar dataKey="count" fill={C.series} radius={[0, 4, 4, 0]} isAnimationActive={false}>
                <LabelList dataKey="count" position="right" style={{ fontSize: 12, fill: C.ink }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  );
}
