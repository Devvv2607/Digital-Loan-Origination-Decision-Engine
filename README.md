# Lendwise (Demo): digital personal-loan origination and decision engine

A working prototype of a digital personal-loan journey: phone OTP, PAN, e-KYC and bank-data consent, an instant rules-based decision with reason codes, a KFS-style offer, e-sign and disbursal, plus the internal tools behind it (credit-policy editor, referral queue, funnel metrics).

> **Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.**
> Lendwise is a fictional lender. Every identity, credit and bank check is simulated, no real money moves, and the KFS-style disclosure is not a legally compliant disclosure or a real offer.

## Live demo

| | Link |
|---|---|
| App | https://digital-loan-origination-decision-e.vercel.app |
| API docs (Swagger) | https://lendwise-demo-api.onrender.com/docs |
| Health check | https://lendwise-demo-api.onrender.com/health |
| Internal tools (read-only) | https://digital-loan-origination-decision-e.vercel.app/internal/metrics |

Start from the landing page with one of five sample applicants (fictional people with synthetic data: strong borrower, new to credit, high FOIR, duplicate PAN, income mismatch). After signing in with a phone OTP, returning applicants see "My applications", and a new application with the same PAN skips e-KYC ("KYC already verified"). The internal tools (`/internal/metrics`, `/internal/referrals`, `/internal/policy`) are public in read-only mode; changes need an ops or admin login. The free API host sleeps when idle (`/ping` is a database-free endpoint for an uptime monitor), so the first request can take up to a minute; the app shows a "Waking up the demo server" notice and retries instead of an error.

## Problem, users, solution

**Problem.** Digital personal loans live or die on a few minutes of applicant patience. Each extra step (identity, credit bureau, bank statements) adds drop-off, and a decision that is slow, opaque or inconsistent loses good borrowers and lets risky ones through. Credit and product teams also need to change policy safely and see where applicants fall out of the funnel.

**Users.** Applicants who want a fast, clear answer; credit-ops analysts who review the cases the engine should not decide alone; credit-policy owners who tune thresholds; and product managers who watch conversion, drop-off and turnaround time.

**Solution.** An eight-state application journey with four simulated integrations (PAN, e-KYC, credit bureau, Account Aggregator), a versioned rules engine (6 eligibility rules, 4 fraud checks) that returns an outcome, reason codes and the policy version for every decision, a KFS-style offer with EMI/APR invariants, and internal tools for policy edits, referral review and metrics. A 500-application simulation runs through the real API to check the engine against expectations defined in advance.

## Architecture

```mermaid
flowchart LR
    subgraph Browser
        A[Applicant journey<br/>Next.js 15 + React 19]
        I[Internal tools<br/>policy, referrals, metrics]
    end
    subgraph Vercel
        F[Next.js frontend]
    end
    subgraph Render
        API[FastAPI<br/>routers + JWT roles + rate limits]
        S[Services<br/>OTP, verification, assessment,<br/>offers, ops review, metrics, expiry]
        E[Decision engine<br/>versioned policy, R1-R6, F1-F4,<br/>pricing, EMI / APR, KFS]
        SM[State machine<br/>8 states + event log]
        M[Mock integrations<br/>PAN, e-KYC, bureau, AA<br/>logged + masked + retries]
    end
    DB[(Neon Postgres<br/>applications, events, decisions,<br/>offers, rule versions, provider calls)]
    GH[GitHub Actions<br/>CI + expiry job every 6 h]
    A --> F
    I --> F
    F -->|HTTPS JSON| API
    API --> S
    S --> E
    S --> SM
    S --> M
    S --> DB
    E --> DB
    GH -->|POST /admin/jobs/expire| API
```

Backend: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, PyJWT. Frontend: Next.js 15, React 19, Tailwind 4, shadcn/ui, Recharts. Tests: pytest (446 tests, 98% coverage) and Playwright.

## State machine

Exactly eight application states; every transition is checked against an allow-list and written to an append-only event log ([docs/STATE_MACHINE.md](docs/STATE_MACHINE.md)).

```mermaid
stateDiagram-v2
    [*] --> DRAFT: POST /applications (phone verified)
    DRAFT --> KYC_PENDING: submit (details valid)
    DRAFT --> EXPIRED: 30 days without activity
    KYC_PENDING --> UNDER_ASSESSMENT: assess (PAN + e-KYC done, AA consent recorded)
    KYC_PENDING --> EXPIRED: 30 days without activity
    UNDER_ASSESSMENT --> APPROVED: engine approves (offer GENERATED)
    UNDER_ASSESSMENT --> REFERRED: engine refers / SYS_* failure
    UNDER_ASSESSMENT --> DECLINED: engine declines
    REFERRED --> APPROVED: analyst approves (offer GENERATED)
    REFERRED --> DECLINED: analyst declines
    APPROVED --> DISBURSED: offer ESIGNED + mock disbursal OK
    APPROVED --> EXPIRED: offer not ESIGNED within 7 days
    DECLINED --> [*]
    DISBURSED --> [*]
    EXPIRED --> [*]
```

Offers move GENERATED → ACCEPTED (KFS acknowledged) → ESIGNED, and an application is DISBURSED only after e-sign.

## Rules and fraud checks

Seed policy version 1 ([docs/RULES.md](docs/RULES.md)). Every parameter is editable from the policy editor; each edit creates a new policy version, and every decision records the version it used.

| ID | Check | Seed policy | Fails to |
|---|---|---|---|
| R1 | Age | at least 21 today, at most 60 at loan maturity | DECLINE `ELIG_AGE` |
| R2 | Credit score | approve ≥ 631; refer 608–630; no history refers | REFER `ELIG_SCORE_BORDERLINE` / `ELIG_THIN_FILE`; DECLINE `ELIG_SCORE_LOW` |
| R3 | Minimum income | ₹25,000 a month (verified, or declared if bank data declined) | DECLINE `ELIG_INCOME_LOW` |
| R4 | FOIR | pass ≤ 50%; refer 50–60%; decline above 60% | REFER / DECLINE `ELIG_FOIR_HIGH` |
| R5 | Employment stability | 6 months salaried, 24 months self-employed | REFER `ELIG_EMPLOYMENT_TENURE` |
| R6 | Loan-to-income cap | 20 × monthly income; counter-offer, then FOIR re-run | INFO `INFO_AMOUNT_CAPPED`; DECLINE `ELIG_AMOUNT_BELOW_MIN` |
| F1 | Duplicate PAN | another active application with the same PAN | blocked at the PAN step (409, neutral message) |
| F2 | Velocity | more than 3 applications from one phone or device in 24 h | REFER `FRAUD_VELOCITY` |
| F3 | Identity mismatch | PAN vs e-KYC name similarity < 0.85, or DOB differs | REFER `FRAUD_IDENTITY_MISMATCH` |
| F4 | Income inconsistency | declared vs verified income differ by more than 30% | REFER `FRAUD_INCOME_MISMATCH` |

DECLINE beats REFER beats APPROVE, every applicable rule is evaluated, and `SYS_`, `DATA_`, `FRAUD_`, `ELIG_` and `INFO_` codes stay separate. Applicants never see fraud reasoning, only a neutral "we need to review a few details".

**How R2 was seeded.** R2 is calibrated to the approval rate from a separate [credit-risk cut-off project](https://github.com/Devvv2607/Credit-Risk-Segmentation-Approval-Cut-off-Strategy), whose recommended cut-off approved 88.2% of its test set. `scripts/seed_policy_from_cutoff.py` takes that 88.2% as a target and sets the R2 thresholds at the matching quantiles of the mock bureau's score distribution (approve 631, refer floor 608, a 5% refer band). The original model's points scale is not the 300–900 bureau scale, so this is an illustrative calibration to an approval-rate scenario. It does not establish equivalent risk, and that project's payment-difficulty rate is not reproduced or claimed.

## Simulation results

500 synthetic applications, designed around 14 personas with expected outcomes fixed in advance, run through the same API endpoints the frontend uses. Figures below are copied from [reports/simulation_report.md](reports/simulation_report.md) (seed 20261022, policy version 1, fixed as-of date 2026-10-22).

**Match rate: 500/500 (100.0%).** A row matches when both the outcome and the full set of reason codes equal the expectation.

| Outcome | Applications | Share of 500 |
|---|---|---|
| APPROVED | 182 | 36.4% |
| REFERRED | 218 | 43.6% |
| DECLINED | 70 | 14.0% |
| BLOCKED_AT_PAN | 20 | 4.0% |
| KYC_PENDING | 10 | 2.0% |

| Stage | Applications | Drop-off from previous |
|---|---|---|
| CREATED | 500 | – |
| SUBMITTED | 500 | 0.0% |
| ASSESSED | 470 | 6.0% |
| APPROVED | 182 | 61.3% |
| DISBURSED | 162 | 11.0% |

Application-to-disbursal conversion: 32.4%. Instant-decision rate: 53.6%. Referral rate: 46.4%. Fraud-flag rate: 15.6% (78 of 500). Approval rate among decided applications: 38.7%. On this test set, 390 of 430 scored applicants (90.7%) scored ≥ 631 on R2.

These rates describe a test set deliberately skewed toward edge cases, not an applicant population. A 100% match shows the engine, state machine and API behave as specified; it does not show production readiness or credit-risk performance (there are no repayment outcomes). To show the check can fail, a one-parameter mutation (FOIR pass threshold 50% → 45%) produced exactly the 16 mismatches predicted from the input data beforehand ([D-43](docs/DECISIONS.md)).

## Screenshots

| | |
|---|---|
| ![Landing page with personas](docs/screenshots/01-landing.png) Landing page and one-click personas | ![Phone and OTP](docs/screenshots/02-phone-otp.png) Phone number and simulated OTP |
| ![Details](docs/screenshots/03-details.png) Personal and loan details | ![PAN](docs/screenshots/04-pan.png) PAN verification |
| ![Duplicate PAN](docs/screenshots/04b-duplicate-pan.png) Duplicate PAN, neutral message | ![e-KYC](docs/screenshots/05-ekyc.png) e-KYC |
| ![Bank data consent](docs/screenshots/06-bank-consent.png) Account Aggregator consent | ![Approved](docs/screenshots/07-decision.png) Instant approval |
| ![Referred](docs/screenshots/07b-referred.png) Referral, plain-language reason | ![KFS offer](docs/screenshots/08-kfs-offer.png) KFS-style offer |
| ![E-sign](docs/screenshots/09-esign.png) E-sign | ![Disbursed](docs/screenshots/10-disbursed.png) Disbursal |
| ![Metrics](docs/screenshots/11-metrics.png) PM metrics dashboard | ![Referral queue](docs/screenshots/12-referral-queue.png) Referral queue |
| ![Referral detail](docs/screenshots/13-referral-detail.png) Referral detail and analyst review | ![Policy editor](docs/screenshots/14-policy-editor.png) Credit-policy editor |
| ![Phone landing](docs/screenshots/15-phone-landing.png) Landing page on a phone | ![Phone metrics](docs/screenshots/16-phone-metrics.png) "Simulated timings" chart on a phone |
| ![My applications](docs/screenshots/17-my-applications.png) "My applications" for a returning applicant; the new application reused e-KYC | |

## Key product decisions

The full log is in [docs/DECISIONS.md](docs/DECISIONS.md) (D-01 to D-47). The ones that shape the product most:

- **Refer, don't decline, when data is missing or thin** (D-08, D-09, D-10). A bureau outage, a declined bank-data consent or a thin credit file sends the case to an analyst instead of turning away a possibly good borrower.
- **Evaluate every rule and keep every reason** (D-11, D-23). Analysts see the full picture; the applicant sees the one most useful reason.
- **Counter-offers re-run affordability** (D-12). A capped amount is only offered if FOIR passes on that amount.
- **Duplicate PAN is an operational block, not a decision** (D-06). The applicant gets a neutral message, and nothing is linked to the PAN.
- **Fraud reasoning is never shown to applicants** (D-16).
- **Policy is versioned, and decisions keep their version** (D-14, D-38, EC-15). An offer accepted after a policy edit still honours the policy it was decided under.
- **R2 is calibrated to an approval-rate scenario, not a risk mapping** (D-13).
- **Public demo is read-only** (D-19, D-39). Anyone can explore the internal tools; names are reduced to initials and writes need a login.
- **Applicants only ever reach their own applications** (D-47). Another applicant's application answers 404, the same as one that doesn't exist; a returning applicant sees "My applications" and reuses e-KYC already done for the same PAN.
- **The deployed demo is seeded, with simulated timings** (D-42, D-44). Visitors see a populated dashboard and queue. Stage durations in the seed are drawn from assumed distributions and labelled "Simulated timings"; the simulation report keeps the real run's timings.

## Limitations

- **Simulated everything.** Data is synthetic, the four integrations are deterministic mocks, OTPs are shown on screen, and e-sign and disbursal are simulated. No real PANs, bureau data or money.
- **Not a production underwriting system.** The rules are illustrative, R2's calibration does not establish risk equivalence, and there are no repayment outcomes to validate against. The KFS-style screen is not a compliant disclosure.
- **Test set, not a population.** The 500 applications over-represent edge cases, so their approval and referral rates are not forecasts.
- **Demo-scale engineering.** Metrics are computed on read, rate limits are in memory on one instance, and the free hosting tier sleeps when idle.
- **Simulated timings on the live dashboard** come from assumed distributions, not observed behaviour. About half the seeded referrals carry simulated analyst reviews, decided by a fixed rule per reason code (D-46); the rest wait in the queue for visitors.
- **Expiry job** runs from a GitHub Actions schedule (every 6 hours), and also lazily whenever an application is opened.

## Run locally

Requires Docker, Python 3.11 and Node 22.

```bash
# Database (Postgres on localhost:55432; dev and test databases)
docker compose up -d --wait db

# Backend
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\
cp .env.example .env                     # replace the change-me values
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:create_app --factory --reload      # http://localhost:8000/docs

# Frontend (another terminal)
cd frontend
cp .env.example .env.local               # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install && npm run dev               # http://localhost:3000
```

Set `DEMO_SEED=true` in `backend/.env` before the first start to load the 500 seeded applications into an empty database, as the deployed demo does.

**Tests**

```bash
cd backend && .venv/bin/python -m pytest --cov          # 446 tests, 98% coverage
cd frontend && npm run build && npm run test:e2e        # happy path, returning applicant, cold-start notice; backend running with CLOCK_START=2026-10-22T09:00:00+05:30
python scripts/check_api_docs.py                        # docs/API.md matches the OpenAPI spec
```

**Simulation** (empty database, backend started with `RATE_LIMIT_PROFILE=simulation` and `CLOCK_START=2026-10-22T09:00:00+05:30`)

```bash
backend/.venv/bin/python scripts/generate_applications.py   # reproduces reports/synthetic_applications.json
backend/.venv/bin/python scripts/run_simulation.py          # writes reports/simulation_report.md
# optional, rebuilding the deployed seed: copy that database, review half the referrals on the copy, then build
backend/.venv/bin/python scripts/review_seed_referrals.py --database-url <copy>   # backend on the copy, CLOCK_START=...T12:00:00+05:30
backend/.venv/bin/python scripts/build_demo_seed.py --database-url <copy>
```

## Deployment

Neon (Postgres) + Render (API, `render.yaml` Blueprint) + Vercel (frontend, root directory `frontend`). On start, the API runs migrations and, with `DEMO_SEED=true` on an empty database, loads policy version 1 and the 500 seeded applications. Secrets live only in the hosts' environment settings. Step-by-step instructions: [DEPLOY.md](DEPLOY.md).

## Documentation

[PRD](docs/PRD.md) · [State machine](docs/STATE_MACHINE.md) · [Rules](docs/RULES.md) · [API](docs/API.md) · [Decisions](docs/DECISIONS.md) · [Traceability](docs/TRACEABILITY.md) · [Simulation report](reports/simulation_report.md)
