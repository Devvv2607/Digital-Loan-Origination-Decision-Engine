# Product and Design Decisions

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.

Each entry records the context, the decision, the alternatives considered and the trade-off. Thresholds are **illustrative values for a fictional lender**; none is taken from any real lender's policy.

---

## Journey and state machine

### D-01 — Fictional brand and persistent disclaimers
- **Decision:** Brand everything as "Lendwise (Demo)", with a persistent banner on every page: *"Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender."* The KFS screen carries its own "not a legally compliant disclosure" label.
- **Why:** The workflow imitates a regulated financial product; nobody should mistake it for a real offer or associate it with a real lender.
- **Trade-off:** Slightly less "real" feel in screenshots; acceptable.

### D-02 — `KYC_PENDING` covers PAN, e-KYC and AA consent; `UNDER_ASSESSMENT` is system-only
- **Context:** The allowed transitions give `UNDER_ASSESSMENT` no path to `EXPIRED`. If the applicant entered `UNDER_ASSESSMENT` after e-KYC and then abandoned the AA consent step, the application could never expire (EC-14).
- **Decision:** The application stays in `KYC_PENDING` through PAN, e-KYC and AA consent. `POST /assess` moves it `KYC_PENDING → UNDER_ASSESSMENT → outcome` inside one request.
- **Alternatives:** (a) Add `UNDER_ASSESSMENT → EXPIRED` — rejected, changes the specified transitions. (b) Move AA consent before e-KYC — rejected, changes the specified journey order.
- **Trade-off:** `KYC_PENDING` is a slightly broader name than its contents ("pre-assessment verification"). In return every applicant-owned step can expire and no one is stranded in a system state. TAT for `UNDER_ASSESSMENT` measures pure engine + bureau time, which is a cleaner metric.

### D-03 — Expired offers are not reopened
- **Decision:** When an offer expires, the application moves to `EXPIRED` (terminal). The applicant must start a new application.
- **Why:** A new application re-runs bureau, fraud and policy checks on current data and current policy. Reopening a stale offer would lend on stale data.
- **Trade-off:** Extra friction for an applicant who simply forgot; mitigated by showing the expiry date clearly on the offer.

### D-04 — Offer expiry applies until e-sign
- **Decision:** An offer in `GENERATED` or `ACCEPTED` expires at `expires_at` (7 days). Once `ESIGNED`, it cannot expire; disbursal can be retried.
- **Why:** Acceptance without a signature is not a binding agreement; a signed agreement should not be silently voided by a timer.

### D-05 — Abandonment measured from last activity; lazy plus bulk expiry
- **Decision:** The 30-day clock runs from the last applicant activity, not from creation. Expiry is applied lazily on every read/action and in bulk via `POST /admin/jobs/expire`. All time comes from an injectable clock.
- **Why:** Measuring from creation would expire someone who is actively working on their application. Lazy expiry works on free hosting tiers without a cron; the bulk job lets the dashboard and simulation see consistent states. The injectable clock makes EC-14 and EC-15 testable without waiting.
- **Production trigger (to do in Phase 7):** Expire-on-read is already built (Phase 1), but on its own it leaves untouched applications in their old state, so dashboard counts drift. In production the bulk job `POST /admin/jobs/expire` needs a scheduled trigger: a Render cron job calling it with an admin token, or an equivalent scheduler. Implementation is deferred to Phase 7.

### D-06 — Duplicate PAN (F1) is an operational block at the PAN step
- **Decision:** If another non-terminal application holds the PAN, `pan/verify` returns HTTP 409 with a neutral message, does not link the PAN, creates no decision and logs a `FRAUD_CHECK` event with `FRAUD_DUPLICATE_PAN`. The blocked application stays in `KYC_PENDING`: the applicant can retry with a corrected PAN (typos happen) or let it expire after 30 days.
- **Why:** Blocking early avoids paying for KYC/bureau calls on a duplicate, and a neutral message avoids tipping off a fraudster while not accusing a genuine applicant who forgot an earlier application.
- **Alternative:** Move the blocked application to `DECLINED` — not an allowed transition from `KYC_PENDING`, and declining a possible typo is harsh.

### D-07 — PAN name mismatch: the applicant chooses (EC-04)
- **Decision:** When the PAN name differs from the entered name (similarity < 0.85), the applicant chooses "Use PAN name" (stored name updated, no flag) or "Keep my entered name" (confirmed mismatch recorded, F3 fires at assessment).
- **Why:** Most mismatches are initials or spelling variants that the applicant can resolve in one tap. Only an insisted mismatch is a fraud signal.

---

## Decision engine

### D-08 — Bureau failure stops evaluation with a `SYS_*` referral (EC-07)
- **Decision:** After 3 attempts (1 + 2 retries), the engine stops and refers with `SYS_BUREAU_UNAVAILABLE`. No credit rule is evaluated or marked failed.
- **Why:** A missing score is not a low score. Declining someone because a provider was down would be unfair and hard to explain.
- **Trade-off:** An applicant who would have been declined on age is referred instead; the analyst sees "rules not evaluated" and decides.

### D-09 — AA consent declined caps the outcome at `REFERRED` (EC-09)
- **Decision:** Declared income is used and still subject to R3/R4/R6; `DATA_INCOME_UNVERIFIED` (REFER) is added. A DECLINE from another rule still wins.
- **Why:** Respects the applicant's choice not to share bank data without auto-approving unverified income. The analyst sees the flag in the queue.

### D-10 — New-to-credit is referred, not declined (EC-08)
- **Why:** No history is not bad history. Declining NTC applicants would exclude first-time borrowers by design.

### D-11 — Evaluate every applicable rule
- **Decision:** No short-circuit after the first failure (except the `SYS_*` stop in D-08).
- **Why:** Complete reason codes help analysts, make declines explainable, and make the simulation's rule fire-frequencies meaningful.
- **Trade-off:** A few extra computations per decision; negligible.

### D-12 — Counter-offers re-run FOIR (R6 → R4)
- **Decision:** If the requested amount exceeds 20× monthly income, the amount is capped (rounded down to the nearest ₹1,000), EMI is recalculated at the same rate and tenure, and R4 runs on the capped amount only. The counter-offer is made only if the overall outcome is APPROVED. `INFO_AMOUNT_CAPPED` is recorded even when R4 still fails, so analysts see the cap.
- **Why:** A counter-offer that is itself unaffordable would be irresponsible.

### D-13 — R2 thresholds come from an approval-rate scenario, not a risk mapping
- **Context:** The reference credit-risk project's scorecard (points scale: base 600 at 50:1 odds, PDO 20) recommended a 535-point cut-off that approved 88.2% of its held-out test set, with a 5.9% payment-difficulty rate vs an 8.07% baseline. Its scale is unrelated to the simulated 300–900 bureau score.
- **Decision:** `seed_policy_from_cutoff.py` sets the R2 approve threshold at the bureau-score percentile that passes the top 88.2% of the mock bureau's **population distribution**, with a refer band covering the next 5%. The original model's scale and cut-off are recorded as metadata only. The script then reports the rates actually produced on the 500 synthetic applications.
- **Why the population, not the 500:** The 500 are deliberately skewed toward edge cases (D-29), so their score distribution is not representative of an applicant population. Calibrating on them would bake the test mix into the policy.
- **Correction (Phase 2):** An earlier draft used 37.3% approval, a 15% refer band and a 3.0% bad rate. Those figures were wrong; the reference project's results are 88.2% approval and a 5.9% payment-difficulty rate.
- **Limits:** No claim of equivalent risk; the 5.9% rate (or any bad rate) is not reproduced (there are no repayment outcomes). Stated in RULES.md §6 and in the seed file's `source` field.

### D-14 — One global policy version, per-rule rows
- **Decision:** Policy version is a single integer; each edit inserts one new row for the edited rule. Version *N* = latest row per rule with `version ≤ N`.
- **Why:** Decisions store one number that fully reproduces the policy used, history is append-only (auditable), and there is no copying of unchanged rules.

### D-15 — Pricing assumptions
- **Decision:** Fee deducted from disbursal (not financed); monthly EMIs in arrears; nearest-rupee rounding (half up) with the final EMI absorbing differences; no GST or insurance; APR = 12 × monthly IRR.
- **Why:** These are the simplest assumptions that make APR meaningfully different from the nominal rate and that can be stated in one line each on the KFS. Using 12 × monthly IRR keeps APR on the same convention as the nominal rate, so "APR > rate when fee > 0" is a clean invariant.

### D-16 — Fraud reasoning is never shown to applicants
- **Decision:** All `FRAUD_*` codes map to "We need to review a few details." Applicant API responses omit fraud codes.
- **Why:** Explaining fraud rules teaches people how to evade them; a neutral message is also fairer to genuine applicants who trip a rule.

### D-23 — Primary reason code priority
- **Decision:** DECLINE-severity `ELIG_*` (rule order) → `SYS_*` → `FRAUD_*` → `DATA_*` → REFER-severity `ELIG_*` → `INFO_*`.
- **Why:** The primary reason should be the one that determined the outcome; for referrals, system and fraud reasons are the most important for an analyst to see first.

### D-24 — DPD and active-loan count are shown, not ruled on
- **Decision:** The bureau's max DPD (12 months) and active loan count appear in the inputs snapshot and referral detail but drive no rule.
- **Why:** The scope fixes exactly 6 eligibility rules. Adding a DPD rule would be the obvious next policy addition and is listed as a limitation.

### D-27 — Age uses the e-KYC date of birth
- **Why:** e-KYC is the most authoritative identity source in the flow. PAN/KYC DOB disagreement is handled separately by F3.

### D-30 — Phone stored as keyed hash plus last 4 digits
- **Decision:** `applicants` stores a keyed hash of the phone number (`phone_hash`, HMAC-SHA256 with `PII_HASH_KEY`) and its last 4 digits (`phone_last4`). The full number is never stored. Internal screens such as the ops referral queue show `******` + last 4 (e.g. `******4321`). All matching — login lookup and the F2 velocity check — uses `phone_hash` only.
- **Why:** The last 4 digits let an analyst tell applicants apart and match a support call, without the database holding a usable phone number. Velocity needs exact matching, which the hash gives.

### D-22 — Velocity window and counting
- **Decision:** F2 counts applications created from the same phone (matched by `phone_hash`, see D-30) **or** the same device ID in the 24 hours up to and including the current one; it fires when that count exceeds 3 (4th and later). Applications blocked by F1 still count.
- **Why:** Blocked attempts are themselves a velocity signal. Device ID is a client-generated identifier sent as `X-Device-Id`.

---

## Integrations, security and operations

### D-17 — Deterministic in-process mocks behind adapters
- **Decision:** Each provider has an interface and a `Mock` implementation called in-process. `/mock/*` HTTP routes expose the same code for Swagger. Behaviour resolves in order: registered fixture (`PUT /mock/profiles/{pan}`) → magic PAN last letter (`X`, `T`, `I`, `M`, `D`, `B`, `N`) → hash of the PAN. A fixture always wins; magic letters only apply to PANs without one.
- **Why:** Calling our own HTTP endpoints from the backend would add latency and failure modes on free hosting. Fixtures mirror how real provider sandboxes publish test identities, and let the simulation set exact persona data through the API. The hash fallback means any well-formed PAN a visitor types still gets a stable result.

### D-31 — Free-typed PANs get a pseudo-random profile; personas are the controlled path
- **Context:** A PAN without a registered fixture gets a hash-derived identity, bureau record and bank income. Its PAN name almost never matches the name the visitor typed, and its income rarely matches their declared income.
- **Decision:** Keep providers realistic: a mock bureau or AA never sees the applicant's declared details. Free-typed PANs therefore usually trigger the EC-04 name confirmation and often F4. The one-click demo personas (Phase 4) register fixtures so each outcome is reproducible, and the landing page will say so.
- **Trade-off:** A visitor who ignores the personas sees more referrals than a real applicant would; in return the mocks behave like independent providers rather than echoing input.

### D-32 — Product limits live in the PRICING policy
- **Decision:** Loan amount and tenure limits, processing fee, rate bands, offer validity, cooling-off and the grievance contact are one versioned `PRICING` row, edited like a rule. The 6-rule count is unchanged: PRICING is configuration, not an eligibility rule.
- **Why:** A policy manager can change the product without a deploy, and every offer still records the exact version it was priced under (EC-15).

### D-33 — R6 cap below the minimum loan declines with `ELIG_AMOUNT_BELOW_MIN`
- **Decision:** If 20x income is below the ₹50,000 minimum loan, R6 cannot make a counter-offer and returns DECLINE with its own code, `ELIG_AMOUNT_BELOW_MIN` (applicant sees: "Based on your income, we can't offer the minimum loan amount right now.").
- **Why:** A distinct code keeps rule-fire counts honest: the Phase 6 report attributes this decline to R6, not R3. Reusing `ELIG_INCOME_LOW` would have double-counted R3. With the default policy, R3 has usually declined such applicants as well, and both codes are then recorded.
- **Revision (Phase 4 prep):** first implemented with `ELIG_INCOME_LOW`; changed to the distinct code before any results were published.

### D-34 — EC-04 shares F3's threshold; F1 can be switched off
- **Decision:** The PAN-step name check (EC-04) uses F3's `name_similarity_min`, so one setting governs "names match". Turning F1 off removes the duplicate-PAN block (it is F1's only setting).
- **Why:** Two separate thresholds for the same question would drift apart.

### D-35 — Frontend on Next.js 15, Tailwind 4 and current shadcn/ui (deviation from "Next.js 14")
- **Context:** The spec names Next.js 14. Every 14.x release, including the last (14.2.35), has open security advisories; npm audit listed 23, two rated critical for remote code execution, fixed only in Next 15.5.24+. The site is public.
- **Decision (approved by the project owner):** Next.js 15 (latest 15.5.x) with React 19, App Router as specified. Tailwind 4 instead of 3, which removes Tailwind 3's vulnerable file-watcher chain; PostCSS is pinned to a patched version via npm `overrides`. shadcn/ui components come from the current shadcn CLI, which builds them on Base UI primitives.
- **Remaining audit findings:** only the dev-only ESLint plugin chain (`eslint-config-next` -> `fast-glob` -> `micromatch` -> `braces`), which reads our own source files and never ships to the browser or server. Recorded here and in the README limitations.

### D-36 — One-click personas get a fresh synthetic PAN per click
- **Decision:** `POST /demo/personas/{id}` registers a mock fixture for a new random PAN on every click and returns prefilled details and a random demo phone number in a synthetic range (stored hashed; no SMS is sent). The Duplicate PAN persona reuses one PAN held by a standing demo application, which is touched on every use so it never expires. Enabled only when `DEMO_MODE=true`.
- **Why:** If personas used fixed PANs, the second visitor to try "Strong borrower" while the first visitor's application was still active would hit the duplicate-PAN block. A test runs every persona through the real API to its promised outcome, so the landing page can't promise something the engine doesn't do.

### D-37 — Applicant decision screen lists only checks that actually ran
- **Decision:** The "What we checked" list shows journey facts (PAN verified, e-KYC complete, bank data shared or not, bureau report requested) plus the applicant-safe reasons. It never shows per-rule pass marks.
- **Why:** When the bureau is down, credit rules are not evaluated (D-08); a per-rule checklist would imply they passed. Rule-level detail stays on the analyst view.

### D-38 — Analyst approvals are priced under the engine decision's policy version
- **Decision:** An analyst's approval creates a MANUAL decision and an offer priced under the policy version of the engine decision that referred it, even if the policy changed since. If the engine stopped early because the bureau was unavailable (no score, no price), the analyst's offer is the requested amount at the PRICING `fallback_rate` (the highest band).
- **Why:** Same rule as EC-15: an application is judged and priced under one policy version from start to finish. With no score there is no risk band, so the conservative rate applies; the analyst can decline instead.
- **Also:** notes are mandatory (at least 10 characters); a referral can be reviewed once (a second, different review returns 409 `ALREADY_REVIEWED`); retries with the same `Idempotency-Key` replay the original result. An analyst decline shows the applicant no engine reasons; the screen says the credit team reviewed it.

### D-39 — Read-only demo view of internal screens shows initials, not names
- **Decision:** Without a sign-in, `/ops/*`, `/admin/rules*` and `/metrics/*` are readable when `DEMO_READ_ONLY=true`, but applicant names are reduced to initials and employer names are hidden; PAN and phone are masked for everyone. Signed-in ops/admin see full names.
- **Why:** A recruiter can explore every internal screen in seconds without credentials, while nothing a visitor typed into the public demo is shown in full to other visitors.

### D-40 — Metrics computed on read from the event log; chart colours validated
- **Decision:** `/metrics/funnel` and `/metrics/tat` compute every figure on request from `applications`, `application_events` and `decisions` (definitions in PRD §7 and returned in the response). Percentiles use linear interpolation between closest ranks. The dashboard's two-series chart uses a teal/amber pair that passed the colour validator (lightness, chroma, colour-blind separation, contrast); outcome colours are status colours and always carry a text label and icon. Every chart has a table view.
- **Trade-off:** Fine for demo volumes; a real system would pre-aggregate.

### D-18 — E-sign and disbursal are simulated internal steps, not integrations
- **Decision:** Mock e-sign and mock disbursal are steps inside the lender's workflow, logged as events, not adapters under `/mock/*`.
- **Why:** The scope specifies exactly 4 mocked integrations (PAN, KYC, bureau, AA). Counting e-sign and disbursal as integrations would change that claim.

### D-19 — Public read-only demo; writes need a login
- **Decision:** With `DEMO_READ_ONLY=true`, internal screens are viewable without login, with names reduced to initials and PAN/phone masked. Policy edits, referral reviews and demo reset need an admin (or ops, for reviews) JWT, with credentials from environment variables.
- **Why:** A recruiter can explore every screen in seconds, and nobody can vandalise the shared demo.

### D-20 — Idempotency by key and by state
- **Decision:** `Idempotency-Key` replays the stored response; independently, each endpoint checks state (e.g. an existing decision is returned instead of creating another).
- **Why:** Keys protect against network retries; state checks protect against clients that forget to send a key.

### D-25 — Referred applications do not auto-expire
- **Decision:** `REFERRED` has no transition to `EXPIRED`, so referrals wait for an analyst. Queue age is shown to drive an ops SLA.
- **Trade-off:** A neglected queue grows indefinitely; acceptable for a prototype, listed as a limitation.

### D-26 — Rate-limit profile for the simulation
- **Decision:** The 500-application run uses `RATE_LIMIT_PROFILE=simulation`, which raises technical per-IP limits only. The OTP resend cap and F2 velocity rule are unchanged.
- **Why:** All 500 applications come from one IP; per-IP limits would otherwise block the run. Business rules must behave exactly as in production.

### D-28 — Endpoints added beyond the specified list
`POST /auth/login`, `POST /applications/{id}/offer/esign`, `POST /applications/{id}/disburse`, `GET /ops/referrals/{id}`, `POST /admin/demo/reset`, `POST /admin/jobs/expire`, `PUT /mock/profiles/{pan}`. Each is needed by a specified requirement (see [API.md §0.8](API.md)).

---

## Thresholds

### D-21 — Rationale for each default threshold

| Parameter | Default | Rationale (illustrative) |
|---|---|---|
| Minimum age (R1) | 21 | Typical minimum for unsecured personal loans; applicants have some income history |
| Max age at maturity (R1) | 60 | Approximates retirement for salaried borrowers, after which salary income may stop |
| Minimum net monthly income (R3) | ₹25,000 | Leaves room for an EMI after essential expenses in an illustrative urban context |
| FOIR pass / refer (R4) | ≤ 50% / ≤ 60% | Half of income committed to debt is a widely used affordability comfort line; a 10-point grey zone goes to a human |
| Employment tenure (R5) | 6 months salaried / 24 months self-employed | Past probation for salaried; self-employed income needs a longer track record |
| Loan-to-income cap (R6) | 20× monthly income | Keeps unsecured exposure under about 1.7 years of income |
| R2 refer band width | 5% of population | A narrow grey zone just below the 88.2% approval line; keeps the referral queue small when the score policy is this lenient |
| Name similarity (F3) | 0.85 | Tolerates initials and spelling variants; catches different people |
| Income difference (F4) | 30% | Tolerates bonuses and variable pay; flags inflated declarations |
| Velocity (F2) | > 3 in 24 h | A genuine applicant rarely needs more than 3 attempts a day |
| OTP validity / attempts / lock / resends | 5 min / 3 / 15 min / 3 per hour | Short validity and few attempts limit brute force; resend cap limits SMS abuse |
| Resume window | 30 days | Long enough for salary-cycle delays; short enough that data is still fresh |
| Offer validity | 7 days | Gives time to read the KFS without lending on stale bureau data |
| Cooling-off | 3 days | Illustrative look-up period shown on the KFS |
| Processing fee | 2% | Illustrative; makes APR visibly higher than the nominal rate |
| Rate bands | 10.99%–21.99% | Illustrative risk-based spread |

---

## Simulation design

### D-29 — Planned persona mix for the 500 synthetic applications
Implemented exactly as planned in `scripts/generate_applications.py` (seed 20261022). Results: `reports/simulation_report.md`.

| Persona | Planned count | % | Expected outcome (from persona definition) |
|---|---|---|---|
| Strong borrower | 145 | 29% | APPROVED |
| Borderline score | 40 | 8% | REFERRED (`ELIG_SCORE_BORDERLINE`) |
| New to credit | 30 | 6% | REFERRED (`ELIG_THIN_FILE`) |
| High FOIR | 35 | 7% | REFERRED or DECLINED (`ELIG_FOIR_HIGH`), by FOIR band |
| Low income | 30 | 6% | DECLINED (`ELIG_INCOME_LOW`) |
| Age-ineligible | 25 | 5% | DECLINED (`ELIG_AGE`) |
| Short job tenure | 30 | 6% | REFERRED (`ELIG_EMPLOYMENT_TENURE`) |
| High loan-to-income | 35 | 7% | APPROVED with `INFO_AMOUNT_CAPPED`, or R4 outcome on capped amount |
| Duplicate PAN | 20 | 4% | Blocked at PAN (409, F1) — no decision |
| Velocity | 20 | 4% | 4th+ application per phone/device: REFERRED (`FRAUD_VELOCITY`) |
| Identity mismatch | 25 | 5% | REFERRED (`FRAUD_IDENTITY_MISMATCH`) |
| Income mismatch | 25 | 5% | REFERRED (`FRAUD_INCOME_MISMATCH`) |
| Integration timeouts | 20 | 4% | KYC timeout: stays `KYC_PENDING`, no decision; bureau timeout: REFERRED (`SYS_BUREAU_UNAVAILABLE`) |
| AA consent declined | 20 | 4% | REFERRED (`DATA_INCOME_UNVERIFIED`) |
| **Total** | **500** | **100%** | |

Because duplicate-PAN and KYC-timeout cases produce no decision, the report's confusion matrix has BLOCKED_AT_PAN and KYC_PENDING alongside approve/refer/decline.

### D-41 — How the 500-application simulation is set up
- **Expectations are fixed before the run.** Each persona's inputs sit clearly inside or outside each threshold of the seeded policy (e.g. FOIR targets 53-57% for the refer band, 66-85% for decline; ages 19.1-20.8 or 56.5-58.5). The only arithmetic shared with the engine is a standard EMI formula, implemented independently in the generator. The run never edits expectations; mismatches are listed and the script exits non-zero.
- **Seeded policy only.** The runner refuses to start unless the API reports policy version 1 with the 11 seed rows and no applications. The report records the policy version and the git commit.
- **As-of date.** Ages are designed around an as-of date (default: the day the data is generated). Margins of months keep the age cases valid for a few weeks; regenerate with `--as-of` for a later run.
- **Velocity:** 4 groups of 5 applications, two sharing a phone (one login session) and two sharing a device ID; the 4th and 5th of each group are expected to be referred.
- **Duplicates:** 20 strong applicants' offers are deliberately left open (not disbursed) so their PANs are still active when the 20 duplicate-PAN cases arrive last. All other approvals are accepted, e-signed and disbursed through the API; referrals stay in the queue.
- **Server settings:** `RATE_LIMIT_PROFILE=simulation` (one IP sends 500 journeys; business limits such as the OTP resend cap are unchanged), `MOCK_LATENCY_MS=20`, default retry backoff. Time-in-state figures therefore reflect processing time, not applicant behaviour.

### D-42 — Deployed demo is seeded with the simulation (to do in Phase 7)
- **Decision (from the project owner):** the deployed database will be seeded with the 500 simulated applications so the metrics dashboard and referral queue have content for visitors. "Reset demo data" must restore that seeded state, not an empty system.
- **Implementation note for Phase 7:** the simulation's results are created through the API, so the seed is best captured as a database snapshot after a clean run (or by re-running the simulation against the deployed API), and the reset action restores it.
