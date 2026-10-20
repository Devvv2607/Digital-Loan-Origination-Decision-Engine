# Product Requirements Document — Lendwise (Demo) Personal Loan Origination

> **Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.**
> "Lendwise (Demo)" is a fictional lender. Nothing in this document describes a real lender's policy.

| | |
|---|---|
| Status | Draft for review (Phase 0) |
| Owner | Product (portfolio project) |
| Related docs | [STATE_MACHINE.md](STATE_MACHINE.md) · [RULES.md](RULES.md) · [API.md](API.md) · [DECISIONS.md](DECISIONS.md) · [TRACEABILITY.md](TRACEABILITY.md) |

---

## 1. Problem statement

Digital personal-loan journeys lose applicants at identity verification and wait times, while lenders must still control credit risk and fraud. The prototype shows a journey that decides instantly for clear cases, routes grey-zone cases to human review, and explains every decision transparently.

## 2. Goals and non-goals

**Goals**
1. A mobile-first applicant journey from phone OTP to (mock) disbursal, with an instant decision for clear cases.
2. A configurable, versioned decision engine: 6 eligibility rules, 4 fraud checks, risk-based pricing and a KFS-style offer.
3. Transparent outcomes: every decision carries reason codes, a plain-English explanation and the policy version used.
4. Internal tools for the three internal personas: policy editor, referral queue, funnel/TAT dashboard.
5. Evidence: 500 synthetic applications run through the real API, with a generated report.

**Non-goals**
- Real integrations, real credit decisions, real money movement or real customer data.
- Regulatory compliance. The KFS screen is a *KFS-style* disclosure for demonstration only.
- Collections, servicing, repayment tracking or any measure of real-world credit risk (there are no repayment outcomes in this simulation).

## 3. Personas

| Persona | Context | Primary need |
|---|---|---|
| **Applicant** | Salaried or self-employed, applying on mobile | Fast, clear answer without paperwork |
| **Credit policy manager** | Owns eligibility thresholds | Change policy quickly and auditably |
| **Credit ops analyst** | Reviews referred applications | All the evidence for a grey-zone case on one screen |
| **Product manager** | Tracks funnel conversion and turnaround time (TAT) | See where applicants drop off and where time is spent |

## 4. Applicant journey

```
Phone + OTP → Details → PAN → e-KYC → AA consent → Decision → KFS offer → Accept + mock e-sign → Disbursed
```

Application states are defined in [STATE_MACHINE.md](STATE_MACHINE.md). In short: `DRAFT` while details are filled, `KYC_PENDING` from submission through PAN, e-KYC and AA consent, `UNDER_ASSESSMENT` while the engine runs, then `APPROVED` / `REFERRED` / `DECLINED`, and finally `DISBURSED` or `EXPIRED`.

---

## 5. User stories (12)

Each story has 3–5 acceptance criteria in Given/When/Then form. Traceability to endpoints, screens and tests is in [TRACEABILITY.md](TRACEABILITY.md).

### US-01 — Start with mobile number and OTP
**As an** applicant, **I want to** start an application with my mobile number and an OTP, **so that** my identity is anchored to a verified phone.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a valid 10-digit mobile number, **when** I request an OTP, **then** a 6-digit OTP valid for 5 minutes is generated and, in demo mode, shown on screen labelled "Simulated OTP — no SMS sent". |
| AC2 | **Given** a correct, unexpired OTP, **when** I submit it, **then** my phone is marked verified, I receive an applicant session, and starting an application creates a `DRAFT` application linked to my phone with a logged creation event. |
| AC3 | **Given** I have entered a wrong OTP 3 times, **when** I try to verify again, **then** verification is locked for 15 minutes and I see when I can retry (EC-01). |
| AC4 | **Given** an OTP older than 5 minutes, **when** I submit it, **then** it is rejected as expired and I can request a new one, up to 3 sends per hour (EC-02). |
| AC5 | **Given** any OTP request or verification, **when** it is logged, **then** my phone number appears only in masked form (e.g. `******0001`). |

### US-02 — Enter personal, employment and loan details
**As an** applicant, **I want to** enter personal, employment and loan details, **so that** the lender can assess me.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a `DRAFT` application, **when** I save my name, date of birth, employment type, employer/business name, months in current job or business, declared net monthly income, loan amount (₹50,000–₹25,00,000), tenure (12–60 months) and purpose, **then** the data is saved and the application stays in `DRAFT`. |
| AC2 | **Given** an invalid field (e.g. amount out of range, future date of birth), **when** I save, **then** I see a field-level error in the standard error shape and the invalid value is not stored. |
| AC3 | **Given** all required fields are valid, **when** I submit, **then** the application moves `DRAFT → KYC_PENDING` and the transition is logged. |
| AC4 | **Given** a repeated submit with the same `Idempotency-Key`, **when** it is processed, **then** the original response is returned and no second transition or application is created. |
| AC5 | **Given** an application that is no longer in `DRAFT`, **when** I try to edit details, **then** the edit is rejected with `INVALID_STATE` (details are locked after submission). |

### US-03 — Verify PAN
**As an** applicant, **I want to** verify my PAN, **so that** my identity is confirmed.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a `KYC_PENDING` application and a PAN in the format `AAAAA9999A`, **when** I verify it, **then** the (mock) PAN service returns name, date of birth and status, and the call is logged with the PAN masked (`ABCDE****F`). |
| AC2 | **Given** a PAN in the wrong format, **when** I enter it, **then** I see an inline validation error and no PAN service call is made (EC-03). |
| AC3 | **Given** the PAN name differs from the name I entered (similarity < 0.85), **when** verification returns, **then** I am asked to either use the PAN name or keep my entered name; keeping it records a confirmed mismatch that feeds fraud check F3 (EC-04). |
| AC4 | **Given** another active (non-terminal) application already uses this PAN, **when** I verify it, **then** I get HTTP 409 with a neutral message ("An application with these details is already in progress"), the PAN is not linked to this application, no decision is created, and the event is logged as fraud check F1 (EC-11). |
| AC5 | **Given** the PAN service reports the PAN as invalid, **when** verification returns, **then** I am asked to check and re-enter it and the application stays in `KYC_PENDING`. |

### US-04 — Complete e-KYC
**As an** applicant, **I want to** complete e-KYC, **so that** I meet KYC requirements without visiting a branch.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a verified PAN, **when** I start e-KYC and enter the (simulated) KYC OTP, **then** my KYC name, date of birth and address are stored and I continue to AA consent. |
| AC2 | **Given** the KYC provider times out, **when** the call fails, **then** it is retried twice with backoff; if it still fails I see "We're having trouble reaching the verification service. We'll notify you when you can continue," and the application stays in `KYC_PENDING` (EC-05). |
| AC3 | **Given** the KYC response is incomplete, **when** it is received, **then** I am asked to retry e-KYC and the application stays in `KYC_PENDING` (EC-06). |
| AC4 | **Given** KYC succeeds, **when** the data is stored, **then** KYC name and date of birth are compared with the PAN data and the similarity result is kept for fraud check F3 (never shown to me). |

### US-05 — Consent to share bank data via Account Aggregator
**As an** applicant, **I want to** give consent to share bank data via Account Aggregator, **so that** my income is verified without uploading documents.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** e-KYC is complete, **when** I view the consent screen, **then** I see the purpose, the data requested (6 months of bank-account credits), the consent validity and a note that this is a simulated AA flow. |
| AC2 | **Given** I approve consent, **when** the (mock) AA returns data, **then** 6 months of income credits and the average monthly income are stored as verified income, with a consent ID and timestamp. |
| AC3 | **Given** I decline consent, **when** I continue, **then** my declared income is used (still subject to R3 and R4), the best possible outcome is `REFERRED` with `DATA_INCOME_UNVERIFIED`, and I was told this before declining (EC-09). |
| AC4 | **Given** verified income differs from declared income by more than 30%, **when** the application is assessed, **then** verified income is used for all income-based rules and fraud check F4 fires (EC-10). |

### US-06 — Instant decision with a clear reason
**As an** applicant, **I want to** get an instant decision with a clear reason, **so that** I'm not left waiting or guessing.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** e-KYC is complete and AA consent is recorded (approved or declined), **when** assessment runs, **then** the bureau is called, fraud checks F2–F4 and rules R1–R6 are all evaluated (no stopping at the first failure), and a decision of `APPROVED`, `REFERRED` or `DECLINED` is stored with all reason codes, the policy version and an inputs snapshot. |
| AC2 | **Given** a decision, **when** I view it, **then** I see the outcome, a polite plain-English reason and next steps; fraud signals are shown only as "We need to review a few details" and internal codes are never shown. |
| AC3 | **Given** the bureau times out after 2 retries, **when** assessment runs, **then** the application is `REFERRED` with `SYS_BUREAU_UNAVAILABLE` and no credit rule is recorded as failed (EC-07). |
| AC4 | **Given** I have no credit history, **when** assessed, **then** I am `REFERRED` with `ELIG_THIN_FILE`, not declined (EC-08); **given** I am under 21 or would be over 60 at maturity, **then** I am `DECLINED` with `ELIG_AGE` (EC-13). |
| AC5 | **Given** a decision already exists, **when** assessment is called again (with or without the same `Idempotency-Key`), **then** the original decision is returned and no duplicate decision or offer is created. |

### US-07 — KFS-style offer
**As an** applicant, **I want to** see a KFS-style offer with APR, EMI, total cost and fees, **so that** I understand the full cost before accepting.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** an `APPROVED` application, **when** I open the offer, **then** I see loan amount, net disbursal, tenure, interest rate, APR, EMI, total interest, total fees, total repayment, an expandable repayment schedule, the 3-day cooling-off period and a grievance contact. |
| AC2 | **Given** the offer screen, **when** it renders, **then** the pricing assumptions are listed and the label "Simulated KFS-style disclosure for demonstration; not a legally compliant disclosure or a real offer" is visible. |
| AC3 | **Given** the requested amount exceeded the loan-to-income cap (R6), **when** I see the offer, **then** the reduced amount is shown next to my requested amount with a plain-English explanation (`INFO_AMOUNT_CAPPED`). |
| AC4 | **Given** an offer, **when** I view it, **then** I see its expiry date (7 days after generation) and I cannot accept it after that date. |
| AC5 | **Given** I have not ticked "I have read the Key Fact Statement", **when** I try to accept, **then** the button is disabled in the UI and the API rejects the request with `KFS_NOT_ACKNOWLEDGED`. |

### US-08 — Accept, e-sign and receive disbursal as separate steps
**As an** applicant, **I want to** accept the offer, e-sign (mock) and receive disbursal (mock), as separate steps, **so that** my loan is disbursed only after I've explicitly agreed and signed.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a `GENERATED` offer and a ticked KFS acknowledgement, **when** I accept, **then** the offer becomes `ACCEPTED`, the event is logged and the application stays `APPROVED`. |
| AC2 | **Given** an `ACCEPTED` offer, **when** I complete the mock e-sign, **then** the offer becomes `ESIGNED` and the event is logged; e-sign on an offer that is not `ACCEPTED` is rejected. |
| AC3 | **Given** an `ESIGNED` offer, **when** the mock disbursal succeeds, **then** the application moves `APPROVED → DISBURSED` and I see the net amount disbursed and the cooling-off information; disbursal before e-sign is rejected. |
| AC4 | **Given** the offer has expired, **when** I try to accept or sign, **then** I get `OFFER_EXPIRED`, the application moves to `EXPIRED`, and I am told to start a new application. |
| AC5 | **Given** the policy changed after my decision, **when** I accept, **then** my offer keeps the terms and `policy_version` from decision time (EC-15). |

### US-09 — Resume an incomplete application
**As an** applicant, **I want to** resume an incomplete application, **so that** I don't lose progress.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** a `DRAFT` or `KYC_PENDING` application with activity in the last 30 days, **when** I verify OTP with the same phone, **then** I am offered to resume it at the first incomplete step with my saved data. |
| AC2 | **Given** no activity on a `DRAFT` or `KYC_PENDING` application for 30 days, **when** it is next read or the expiry job runs, **then** it moves to `EXPIRED` (actor `system`, reason `ABANDONED_30D`) and I must start a new application (EC-14). |
| AC3 | **Given** an application in `APPROVED`, `REFERRED` or `DECLINED`, **when** I return, **then** I see the matching screen (offer, "under review" or decision). |
| AC4 | **Given** a session for a different phone, **when** it requests my application, **then** access is refused (403). |

### US-10 — Edit rule thresholds without a code deploy
**As a** credit policy manager, **I want to** edit rule thresholds without a code deploy, with versioning, **so that** policy can change quickly and auditably.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** I am logged in as admin, **when** I change a rule's parameters, enabled flag or fail outcome and save with a comment, **then** a new policy version is created, previous versions are kept, and the change records who, when and why. |
| AC2 | **Given** invalid parameters (e.g. refer floor above approve threshold, FOIR refer limit above decline limit), **when** I save, **then** the change is rejected with field-level errors and no version is created. |
| AC3 | **Given** a new policy version, **when** the next application is assessed, **then** it uses the new version without a restart; existing decisions and offers keep the version they were made under. |
| AC4 | **Given** the version history, **when** I select two versions, **then** I see a diff of changed parameters. |
| AC5 | **Given** I am in read-only demo mode, **when** I open the policy editor, **then** I can view rules and history but every edit control is disabled and write requests are refused (401/403). |

### US-11 — Review referred applications
**As a** credit ops analyst, **I want to** review referred applications and approve or decline with notes, **so that** grey-zone cases get human judgement.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** referred applications exist, **when** I open the queue, **then** I see a paginated list, oldest first, with primary reason, all reason codes and time in queue. |
| AC2 | **Given** a referred application, **when** I open it, **then** I see every reason code with its explanation, the inputs snapshot, fraud signals, masked integration results, and a clear `DATA_INCOME_UNVERIFIED` flag when AA consent was declined. |
| AC3 | **Given** I approve with notes, **when** I submit, **then** the application moves `REFERRED → APPROVED`, an offer is generated under the decision's policy version, and my review is stored; declining with notes moves it to `DECLINED`. Notes are mandatory. |
| AC4 | **Given** a review already recorded, **when** a second review is submitted (or the same request is retried), **then** a retry with the same `Idempotency-Key` returns the original result and a different second review is rejected with 409. |
| AC5 | **Given** I am not logged in as ops or admin, **when** I try to review, **then** the request is refused; read-only viewers can see the queue only. |

### US-12 — Funnel conversion and TAT per stage
**As a** product manager, **I want to** see funnel conversion and TAT per stage, **so that** I can find and fix drop-offs.

| # | Acceptance criterion |
|---|---|
| AC1 | **Given** applications exist, **when** I open the dashboard, **then** I see counts per funnel stage and application-to-disbursal conversion. |
| AC2 | **Given** the funnel, **when** I view drop-off, **then** I see the share of applications lost at each stage. |
| AC3 | **Given** `application_events`, **when** TAT is computed, **then** I see median and 90th-percentile time spent in each state. |
| AC4 | **Given** decisions exist, **when** I view the decision panel, **then** I see decision mix, instant-decision rate, referral rate, fraud-flag rate and top reason codes, filterable by date range. |
| AC5 | **Given** any metric on the dashboard, **when** I hover its info icon, **then** I see its definition (as in §7). |

---

## 6. Edge cases (15)

Every edge case has handling code and at least one test named `test_ec_XX_*`. Test names below are planned and will be confirmed in [TRACEABILITY.md](TRACEABILITY.md).

| ID | Edge case | Expected behaviour | Resulting state | Applicant sees | Planned test |
|---|---|---|---|---|---|
| EC-01 | Wrong OTP entered 3 times | Lock OTP verification for that phone for 15 minutes; correct OTP also refused while locked | No application change | "Too many attempts. Try again after HH:MM." | `test_ec_01_otp_locked_after_three_wrong_attempts` |
| EC-02 | OTP expired (>5 min) | Reject; allow resend, max 3 sends per phone per rolling hour | No application change | "This code has expired. Request a new one." | `test_ec_02_expired_otp_rejected_and_resend_capped` |
| EC-03 | Invalid PAN format | Inline validation (client and server); no provider call, no `integration_calls` row | `KYC_PENDING` | "Enter PAN as 5 letters, 4 digits, 1 letter." | `test_ec_03_invalid_pan_format_makes_no_provider_call` |
| EC-04 | PAN name doesn't match entered name | Ask applicant to use PAN name or keep entered name; keeping it records a confirmed mismatch that feeds F3 | `KYC_PENDING` | "The name on your PAN looks different. Which is your legal name?" | `test_ec_04_pan_name_mismatch_requires_confirmation_and_feeds_f3` |
| EC-05 | KYC provider timeout | Retry ×2 with backoff (3 attempts, all logged); then stay in `KYC_PENDING` | `KYC_PENDING` | "We're having trouble reaching the verification service. We'll notify you." | `test_ec_05_kyc_timeout_retries_then_stays_pending` |
| EC-06 | KYC response incomplete | Ask applicant to retry e-KYC | `KYC_PENDING` | "We couldn't complete e-KYC. Please try again." | `test_ec_06_kyc_incomplete_asks_retry` |
| EC-07 | Credit bureau timeout | Retry ×2; then refer with `SYS_BUREAU_UNAVAILABLE`; credit rules not evaluated or marked failed | `REFERRED` | "Your application needs a quick review. We'll update you soon." | `test_ec_07_bureau_timeout_refers_with_sys_code` |
| EC-08 | No credit history (NTC) | R2 returns REFER with `ELIG_THIN_FILE` | `REFERRED` | "Our team will review your application." | `test_ec_08_ntc_refers_not_declines` |
| EC-09 | AA consent declined | Use declared income (still subject to R3/R4); add `DATA_INCOME_UNVERIFIED` (REFER); flagged in referral queue | `REFERRED` (or `DECLINED` if a decline rule fires) | "Without bank data we need to review your income manually." | `test_ec_09_aa_declined_caps_at_referred` |
| EC-10 | AA income differs from declared by >30% | Use verified income for R3/R4/R6; F4 fires (REFER) | `REFERRED` (or `DECLINED` if a decline rule fires on verified income) | "We need to review a few details." | `test_ec_10_income_mismatch_uses_verified_and_flags_f4` |
| EC-11 | Active application already exists for this PAN | HTTP 409 with neutral message; PAN not linked; no decision; logged as F1 `FRAUD_DUPLICATE_PAN` | `KYC_PENDING` (unchanged) | "An application with these details is already in progress." | `test_ec_11_duplicate_pan_blocked_with_409` |
| EC-12 | >3 applications from same phone/device in 24h | F2 fires (REFER) on the 4th and later applications | `REFERRED` | "We need to review a few details." | `test_ec_12_velocity_flags_fourth_application` |
| EC-13 | Age <21 now or >60 at maturity | R1 DECLINE `ELIG_AGE` | `DECLINED` | "You don't meet our age criteria for this loan." | `test_ec_13_age_out_of_range_declines` |
| EC-14 | Application abandoned mid-flow | Resumable for 30 days from last activity; then `EXPIRED` by system | `EXPIRED` | "This application has expired. Please start a new one." | `test_ec_14_abandoned_application_expires_after_30_days` |
| EC-15 | Policy changes between decision and acceptance | Offer stores `policy_version`, `expires_at`, status; acceptance honours decision-time terms; offer expires after 7 days | `APPROVED` → `DISBURSED` (or `EXPIRED`) | Original offer terms | `test_ec_15_acceptance_honours_decision_time_policy` |

---

## 7. Success metrics (PM dashboard)

All metrics are computed from `applications`, `application_events` and `decisions`. In the simulation they describe synthetic behaviour only.

| Metric | Definition |
|---|---|
| **Application-to-disbursal conversion** | Applications that reached `DISBURSED` ÷ applications created (`DRAFT`), in the selected period. |
| **Stage-wise drop-off** | For each funnel stage (Created → Submitted → Assessed → Approved → Disbursed): 1 − (applications reaching the next stage ÷ applications reaching this stage). Approved includes approvals after referral. |
| **Median / P90 TAT per stage** | For each state, the time between entering it and leaving it, from `application_events`; median and 90th percentile over applications that have left that state. |
| **Instant-decision rate** | Engine decisions with outcome `APPROVED` or `DECLINED` ÷ all engine decisions (excludes analyst decisions). |
| **Referral rate** | Engine decisions with outcome `REFERRED` ÷ all engine decisions. |
| **Fraud-flag rate** | Applications with at least one `FRAUD_*` signal (including F1 blocks at PAN) ÷ applications that attempted PAN verification. |
| **Top reason codes** | Count of each reason code across engine decisions, descending. |

## 8. Functional summary

- **Integrations (4, all mocked):** PAN, e-KYC, credit bureau, Account Aggregator. Deterministic, latency configurable via `MOCK_LATENCY_MS`, every call logged to `integration_calls` with PAN/phone masked. Exposed under `/mock/*` in Swagger.
- **Decision engine:** 6 eligibility rules (R1–R6) and 4 fraud checks (F1–F4) configured in a versioned `rule_configs` table; full specification in [RULES.md](RULES.md).
- **Outcomes:** `APPROVED` / `REFERRED` / `DECLINED` with reason codes from five distinct families (`SYS_`, `DATA_`, `FRAUD_`, `ELIG_`, `INFO_`) and a KFS-style offer for approvals.
- **Offer lifecycle:** `GENERATED → ACCEPTED → ESIGNED`, then mock disbursal moves the application to `DISBURSED`.

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Disclosure | Persistent demo banner on every page; fictional brand "Lendwise (Demo)" only |
| Security | Roles: applicant, ops, admin (JWT). Public read-only demo for internal screens; writes need login via environment-configured credentials |
| Privacy | PAN masked `ABCDE****F`, phone masked `******0001` in logs and `integration_calls`; no real PANs, phones or secrets in the repo |
| Reliability | Idempotency on submit, assess, offer accept and referral review; provider failures land the application in a defined state with a friendly message |
| Abuse | Rate limits on OTP send/verify, application creation and `/mock/*` |
| Performance | Engine decision (excluding simulated provider latency) under 1 second locally |
| Accessibility | Mobile-first, keyboard navigable, labelled form fields, visible loading state on every mock call |
| Quality | ≥80% backend test coverage (actual figure reported in README) |

## 10. Out of scope

Real SMS, real e-sign or payment rails; Aadhaar numbers or biometric data (e-KYC is an OTP-only mock); servicing and collections; multi-product support; GST on fees; notifications beyond on-screen messages (the "we'll notify you" message is simulated).

## 11. Open questions for review

1. **Credit-risk project metadata:** the original scorecard's score scale and cut-off value, and the repository link, to record as metadata in the R2 seeding script (see [RULES.md §6](RULES.md#6-seeding-r2-from-the-credit-risk-cut-off-project)).
2. Confirm the interpretation that `KYC_PENDING` covers PAN, e-KYC **and** AA consent, so `UNDER_ASSESSMENT` is a short system-only state (see [DECISIONS.md D-02](DECISIONS.md)).
3. Confirm the added endpoints listed in [API.md §0.8](API.md) (e-sign, disbursal, login, demo reset, expiry job, referral detail, mock fixtures).
