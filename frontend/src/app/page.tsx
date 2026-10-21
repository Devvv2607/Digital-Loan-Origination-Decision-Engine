import Link from "next/link";

import { PersonaList } from "@/components/landing/persona-list";
import { SampleDecision } from "@/components/landing/sample-decision";
import { API_URL } from "@/lib/api";

const JOURNEY = [
  ["Verify your phone", "A one-time code, shown on screen instead of sent by SMS."],
  ["Tell us about you and the loan", "Income, job and how much you want to borrow."],
  ["Verify your PAN", "Checked by a simulated PAN service; a PAN already in use is stopped here."],
  ["Complete e-KYC", "Name, date of birth and address from a simulated identity provider."],
  ["Share bank data, or don't", "Six months of income credits via a simulated Account Aggregator."],
  ["Get a decision", "Approve, refer to an analyst, or decline, with the reasons in plain English."],
  ["Read the Key Fact Statement", "Rate, APR, EMI, fees and total cost before you agree to anything."],
  ["Accept, e-sign, receive the money", "Three separate steps; nothing is paid out until you have signed."],
];

const SIMULATED = [
  ["PAN verification", "Name, date of birth and status for a PAN."],
  ["e-KYC", "OTP-based identity check that can time out or come back incomplete."],
  ["Credit bureau", "Score from 300 to 900, existing EMIs, or no history at all."],
  ["Account Aggregator", "Consent to share bank data, then six months of income credits."],
];

export default function Home() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4">
      <section className="grid gap-10 py-12 md:grid-cols-[1.1fr_1fr] md:items-center md:py-16">
        <div className="space-y-5">
          <h1 className="max-w-[18ch] text-[2.1rem] leading-[1.1] font-semibold tracking-tight text-balance sm:text-[2.6rem]">
            See how a personal loan decision gets made
          </h1>
          <p className="max-w-[52ch] text-[1.05rem] leading-relaxed text-muted-foreground">
            Apply as one of five ready-made applicants, or as yourself. Identity, credit bureau and bank-data checks
            are all simulated, and every decision comes with the reasons behind it.
          </p>
          <div className="flex flex-wrap gap-3">
            <a
              href="#personas"
              className="inline-flex h-11 items-center rounded-lg bg-primary px-5 text-[0.95rem] font-medium text-primary-foreground hover:bg-primary/90"
            >
              Pick an applicant
            </a>
            <Link
              href="/apply"
              className="inline-flex h-11 items-center rounded-lg border border-input bg-card px-5 text-[0.95rem] font-medium hover:bg-muted"
            >
              Apply as yourself
            </Link>
            <Link
              href="/internal/referrals"
              className="inline-flex h-11 items-center px-1 text-[0.95rem] font-medium text-primary underline underline-offset-4"
            >
              View as ops or admin (read-only)
            </Link>
          </div>
        </div>
        <SampleDecision />
      </section>

      <section id="personas" aria-labelledby="personas-title" className="scroll-mt-6 border-t border-border py-10">
        <h2 id="personas-title" className="text-xl font-semibold tracking-tight">
          Try it as one of these applicants
        </h2>
        <p className="mt-2 max-w-[60ch] text-muted-foreground">
          Each one fills in the forms for you and leads to a different outcome. You still click through every step,
          so you see what the applicant sees. A full run takes under a minute.
        </p>
        <PersonaList />
      </section>

      <section aria-labelledby="journey-title" className="grid gap-10 border-t border-border py-10 md:grid-cols-2">
        <div>
          <h2 id="journey-title" className="text-xl font-semibold tracking-tight">
            The journey
          </h2>
          <ol className="mt-5 space-y-4">
            {JOURNEY.map(([title, text], i) => (
              <li key={title} className="grid grid-cols-[1.75rem_1fr] gap-x-3">
                <span className="figures pt-0.5 text-sm font-semibold text-primary" aria-hidden>
                  {i + 1}
                </span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-muted-foreground">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h2 className="text-xl font-semibold tracking-tight">What is simulated</h2>
          <p className="mt-2 text-muted-foreground">
            Four mock providers stand in for real integrations. They behave the same way every time, so each outcome
            can be reproduced and tested.
          </p>
          <dl className="mt-5 divide-y divide-border rounded-lg border border-border bg-card">
            {SIMULATED.map(([name, text]) => (
              <div key={name} className="px-4 py-3">
                <dt className="font-medium">{name}</dt>
                <dd className="text-sm text-muted-foreground">{text}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-5 text-sm text-muted-foreground">
            Decisions come from 6 eligibility rules and 4 fraud checks whose thresholds are versioned and editable
            without a code change. The API is documented in{" "}
            <a className="text-primary underline underline-offset-2" href={`${API_URL}/docs`}>
              Swagger
            </a>
            , and the code is on{" "}
            <a
              className="text-primary underline underline-offset-2"
              href="https://github.com/Devvv2607/Digital-Loan-Origination-Decision-Engine"
            >
              GitHub
            </a>
            .
          </p>
        </div>
      </section>
    </div>
  );
}
