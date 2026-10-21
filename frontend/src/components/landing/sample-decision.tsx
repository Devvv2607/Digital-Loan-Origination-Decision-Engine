import { OutcomeMark } from "@/components/outcome-mark";

/** Static illustration of a real decision (the Strong borrower persona), used in the hero. */
export function SampleDecision() {
  const checks = [
    ["PAN verified", "Name matches the PAN record"],
    ["e-KYC complete", "Identity confirmed"],
    ["Bank data shared", "Verified income ₹84,200 a month"],
    ["Credit bureau", "Score 781, existing EMIs ₹6,000"],
    ["Affordability", "Repayments would be 27% of income"],
  ];
  return (
    <figure aria-label="Example decision" className="rounded-xl border border-border bg-card p-5 shadow-[0_1px_0_#d6dee7]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">Application from Asha Verma</p>
          <p className="mt-1 text-lg font-semibold">Approved for ₹5,00,000</p>
        </div>
        <OutcomeMark outcome="APPROVED" />
      </div>
      <ul className="mt-4 divide-y divide-border border-t border-border text-sm">
        {checks.map(([name, detail]) => (
          <li key={name} className="flex items-baseline justify-between gap-4 py-2.5">
            <span className="font-medium">{name}</span>
            <span className="text-right text-muted-foreground">{detail}</span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-3 text-xs text-muted-foreground">
        Example from a demo applicant. 12.99% a year, APR 14.41%, EMI ₹16,845 for 36 months.
      </figcaption>
    </figure>
  );
}
