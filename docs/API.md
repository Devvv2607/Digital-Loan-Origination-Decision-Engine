# API Contracts (draft)

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.
> Status: **Phase 0 draft.** The generated OpenAPI spec at `/docs` (Swagger) and `/openapi.json` becomes the source of truth once the backend exists; this file will be reconciled with it in Phase 7.

All example PANs, phone numbers and names are synthetic. Example PANs use the prefix `ZZZPZ` and example phones start `90000`.

---

## 0. Conventions

### 0.1 Base URL and format
- Local: `http://localhost:8000` · Production: Render URL (Phase 7).
- JSON request and response bodies; amounts in whole rupees (integers); rates as percentages with two decimals (`13.49`); timestamps ISO-8601 UTC.

### 0.2 Authentication and roles

| Role | How obtained | Can do |
|---|---|---|
| `public` | No token | `GET /health`, OTP endpoints, read-only internal views when `DEMO_READ_ONLY=true`, `/mock/*` (rate-limited) |
| `applicant` | `POST /auth/otp/verify` → JWT (`sub` = applicant ID) | Create and act on **own** applications only |
| `ops` | `POST /auth/login` with `OPS_USERNAME`/`OPS_PASSWORD` | Review referrals; read admin and metrics views |
| `admin` | `POST /auth/login` with `ADMIN_USERNAME`/`ADMIN_PASSWORD` | Everything ops can do, plus edit policy, reset demo data, run expiry job, register mock fixtures |

Header: `Authorization: Bearer <jwt>`. Credentials come from environment variables only; startup fails if required variables are missing.

**Read-only demo mode** ("View as Ops / Admin"): with `DEMO_READ_ONLY=true`, the `GET` endpoints for `/admin/*`, `/ops/*` and `/metrics/*` are available without a token, with names reduced to initials and PAN/phone masked. All writes still need an ops/admin token.

### 0.3 Error shape

Every error uses one shape:

```json
{
  "error_code": "OTP_LOCKED",
  "message": "Too many attempts. Try again after 14:35.",
  "details": {"locked_until": "2026-10-20T09:05:00Z"}
}
```

| HTTP | `error_code` | When |
|---|---|---|
| 400 | `OTP_INVALID` | Wrong OTP |
| 400 | `OTP_EXPIRED` | OTP older than 5 minutes (EC-02) |
| 400 | `KYC_OTP_INVALID` | Wrong KYC OTP |
| 400 | `KFS_NOT_ACKNOWLEDGED` | Accept without KFS acknowledgement |
| 401 | `UNAUTHENTICATED` | Missing/invalid token |
| 403 | `FORBIDDEN` | Wrong role, or another applicant's application |
| 404 | `NOT_FOUND` | Unknown resource |
| 409 | `INVALID_STATE_TRANSITION` | Action not allowed in current state |
| 409 | `APPLICATION_ALREADY_IN_PROGRESS` | Duplicate PAN (EC-11, F1) — neutral wording |
| 409 | `OFFER_EXPIRED` | Offer past `expires_at` |
| 409 | `ALREADY_REVIEWED` | Second, different review on a referral |
| 409 | `APPLICATION_EXPIRED` | Acting on an expired application |
| 422 | `VALIDATION_ERROR` | Field validation; `details.fields` lists each field error |
| 422 | `PAN_FORMAT_INVALID` | PAN not `AAAAA9999A` (EC-03); no provider call made |
| 422 | `IDEMPOTENCY_KEY_REUSED` | Same key, different request body |
| 422 | `POLICY_VALIDATION_ERROR` | Invalid rule parameters |
| 423 | `OTP_LOCKED` | 3 wrong attempts (EC-01) |
| 429 | `OTP_RESEND_LIMIT` | More than 3 sends per phone per hour (EC-02) |
| 429 | `RATE_LIMITED` | Technical rate limit hit |
| 503 | `DEPENDENCY_UNAVAILABLE` | Database unavailable (`/health`) |

Provider timeouts are **not** errors to the applicant: they return `200`/`202` with a status the UI explains (see KYC and assess below).

### 0.4 Idempotency
`POST /applications/{id}/submit`, `/assess`, `/offer/accept`, `/offer/esign`, `/disburse` and `POST /ops/referrals/{id}/review` accept an `Idempotency-Key` header (any string up to 128 characters, e.g. a UUID).
- Same key + same body → the original status code and body are returned; nothing is written again. Response header `Idempotent-Replay: true`.
- Same key + different body → `422 IDEMPOTENCY_KEY_REUSED`.
- Keys are stored per (endpoint, application) for 24 hours.
- Independently of keys, these endpoints are **naturally idempotent**: e.g. `assess` on an application that already has a decision returns that decision; it never creates a second decision or offer.

### 0.5 Pagination
List endpoints take `?page=1&page_size=20` (max 100) and return:
```json
{"items": [], "page": 1, "page_size": 20, "total": 0}
```

### 0.6 Rate limits (defaults, configurable)

| Endpoint group | Limit |
|---|---|
| `POST /auth/otp/send` | 5 per minute per IP (plus business limit: 3 sends per phone per hour) |
| `POST /auth/otp/verify` | 10 per minute per IP |
| `POST /applications` | 10 per minute per IP |
| `/mock/*` | 30 per minute per IP |

The simulation runs locally with `RATE_LIMIT_PROFILE=simulation` (higher technical limits). Business rules — OTP resend cap and F2 velocity — are never relaxed.

### 0.7 Masking
PAN → `ZZZPZ****Q`; phone → `******0001`. Applied in API responses to non-owners, logs, `integration_calls` and `application_events.metadata`.

### 0.8 Endpoints added beyond the original list (for review)

| Endpoint | Why |
|---|---|
| `POST /auth/login` | Ops/admin JWT login (required by §8b roles) |
| `POST /applications/{id}/offer/esign` | US-08 needs e-sign as a separate step |
| `POST /applications/{id}/disburse` | US-08 needs disbursal as a separate step |
| `GET /ops/referrals/{id}` | Referral detail screen (reason codes + integration results) |
| `POST /admin/demo/reset` | "Reset demo data" admin action (§8b) |
| `POST /admin/jobs/expire` | Bulk expiry for EC-14 / offer expiry; usable by a scheduler and tests |
| `PUT /mock/profiles/{pan}` | Registers deterministic mock fixtures for demo personas and the 500-application simulation |

---

## 1. Health

### `GET /health` — public
Checks database connectivity.

`200`
```json
{"status": "ok", "database": "ok", "version": "0.1.0", "policy_version": 1}
```
`503` → `DEPENDENCY_UNAVAILABLE` with `{"status": "degraded", "database": "unreachable"}` in `details`.

---

## 2. Auth

### `POST /auth/otp/send` — public
```json
{"phone": "9000000001"}
```
`200`
```json
{
  "otp_request_id": "6f1c2a0e-1b7e-4a51-9a3a-0d5b1f2f7c11",
  "expires_at": "2026-10-20T09:05:00Z",
  "resends_remaining_this_hour": 2,
  "demo_otp": "482913",
  "demo_notice": "Simulated OTP — no SMS sent."
}
```
`demo_otp` is present only when `DEMO_MODE=true`. Errors: `422 VALIDATION_ERROR`, `429 OTP_RESEND_LIMIT`, `423 OTP_LOCKED`, `429 RATE_LIMITED`.

### `POST /auth/otp/verify` — public
```json
{"phone": "9000000001", "otp": "482913"}
```
`200`
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "role": "applicant",
  "applicant_id": "2b0e8a4c-5d21-4c8b-9a0f-3e4b7d9c1a22",
  "resumable_applications": [
    {"id": "a3c9...", "state": "KYC_PENDING", "next_step": "EKYC", "last_activity_at": "2026-10-18T11:00:00Z"}
  ]
}
```
Errors: `400 OTP_INVALID` (`details.attempts_remaining`), `400 OTP_EXPIRED`, `423 OTP_LOCKED` (`details.locked_until`).

### `POST /auth/login` — public *(added)*
```json
{"username": "admin", "password": "••••••••"}
```
`200`
```json
{"access_token": "eyJhbGciOi...", "token_type": "bearer", "role": "admin", "expires_in": 3600}
```
Errors: `401 UNAUTHENTICATED`, `429 RATE_LIMITED`.

---

## 3. Applications — applicant

### `POST /applications` — applicant
Header `X-Device-Id: <client-generated device ID>` (used by F2).
```json
{}
```
`201`
```json
{"id": "a3c9d1f2-7e44-4f6b-8c2d-1b2a3c4d5e6f", "state": "DRAFT", "created_at": "2026-10-20T09:00:30Z"}
```

### `GET /applications/{id}` — applicant (owner)
Includes saved details, current step and the event timeline (used for resume and by the simulation's transition checks).

`200`
```json
{
  "id": "a3c9d1f2-...",
  "state": "KYC_PENDING",
  "next_step": "EKYC",
  "details": {
    "full_name": "Asha Verma", "date_of_birth": "1994-03-12",
    "employment_type": "SALARIED", "employer_name": "Example Systems Pvt Ltd",
    "months_in_current_job": 30, "declared_monthly_income": 85000,
    "loan_amount": 500000, "tenure_months": 36, "purpose": "HOME_RENOVATION"
  },
  "pan": {"masked": "ZZZPZ****Q", "status": "VERIFIED"},
  "kyc": {"status": "PENDING"},
  "aa": {"status": "NOT_STARTED"},
  "policy_version": null,
  "last_activity_at": "2026-10-20T09:03:10Z",
  "timeline": [
    {"event_type": "STATE_CHANGE", "from_state": null, "to_state": "DRAFT", "actor": "applicant", "reason": null, "created_at": "2026-10-20T09:00:30Z"},
    {"event_type": "STATE_CHANGE", "from_state": "DRAFT", "to_state": "KYC_PENDING", "actor": "applicant", "reason": "SUBMITTED", "created_at": "2026-10-20T09:02:00Z"}
  ]
}
```
Errors: `403 FORBIDDEN`, `404 NOT_FOUND`. An abandoned application is expired lazily on read and returned with `state: "EXPIRED"`.

### `PATCH /applications/{id}` — applicant (owner), `DRAFT` only
Partial update of `details`.
```json
{"loan_amount": 600000, "tenure_months": 48}
```
`200` → same shape as `GET`. Errors: `422 VALIDATION_ERROR`, `409 INVALID_STATE_TRANSITION` (not `DRAFT`).

### `POST /applications/{id}/submit` — applicant, idempotent
`200`
```json
{"id": "a3c9...", "state": "KYC_PENDING", "next_step": "PAN"}
```
Errors: `422 VALIDATION_ERROR` (`details.missing_fields`), `409 INVALID_STATE_TRANSITION`.

### `POST /applications/{id}/pan/verify` — applicant, `KYC_PENDING`
```json
{"pan": "ZZZPZ1234Q"}
```
`200` — verified, names match
```json
{"status": "VERIFIED", "pan_masked": "ZZZPZ****Q", "name_on_pan": "ASHA VERMA", "next_step": "EKYC"}
```
`200` — name differs (EC-04)
```json
{
  "status": "NAME_CONFIRMATION_REQUIRED",
  "name_on_pan": "ASHA R VERMA",
  "name_entered": "Asha Verma",
  "options": ["USE_PAN_NAME", "KEEP_ENTERED_NAME"]
}
```
Repeat the call with `{"pan": "ZZZPZ1234Q", "name_confirmation": "USE_PAN_NAME"}` (updates the stored name, no flag) or `"KEEP_ENTERED_NAME"` (records a confirmed mismatch that feeds F3).

`200` — PAN reported invalid by provider
```json
{"status": "INVALID", "message": "We couldn't verify this PAN. Please check and try again."}
```
Errors:
- `422 PAN_FORMAT_INVALID` (EC-03) — no provider call, no `integration_calls` row.
- `409 APPLICATION_ALREADY_IN_PROGRESS` (EC-11) — neutral message: "An application with these details is already in progress. Please continue that application." Internally logs a `FRAUD_CHECK` event with `FRAUD_DUPLICATE_PAN`.

### `POST /applications/{id}/kyc/start` — applicant, `KYC_PENDING`, PAN verified
`200`
```json
{"kyc_session_id": "k-7d1e...", "status": "OTP_SENT", "demo_kyc_otp": "601245", "demo_notice": "Simulated e-KYC — no real identity data is used."}
```

### `POST /applications/{id}/kyc/complete` — applicant
```json
{"kyc_session_id": "k-7d1e...", "otp": "601245"}
```
`200` — success
```json
{"status": "COMPLETE", "next_step": "AA_CONSENT"}
```
`202` — provider timeout after 3 attempts (EC-05)
```json
{"status": "DELAYED", "message": "We're having trouble reaching the verification service. We'll notify you when you can continue.", "state": "KYC_PENDING"}
```
`200` — incomplete response (EC-06)
```json
{"status": "INCOMPLETE", "message": "We couldn't complete e-KYC. Please try again.", "state": "KYC_PENDING"}
```
Errors: `400 KYC_OTP_INVALID`, `409 INVALID_STATE_TRANSITION`.

### `POST /applications/{id}/aa/consent` — applicant, `KYC_PENDING`, KYC complete
```json
{"decision": "APPROVE"}
```
`200` — approved
```json
{
  "consent_id": "aa-c-91f3...",
  "status": "APPROVED",
  "months_of_data": 6,
  "average_monthly_income": 84200,
  "next_step": "ASSESS"
}
```
`200` — declined (EC-09)
```json
{"consent_id": "aa-c-91f3...", "status": "DECLINED", "notice": "We'll use the income you declared. Your application will need a manual review.", "next_step": "ASSESS"}
```

### `POST /applications/{id}/assess` — applicant, idempotent
Moves `KYC_PENDING → UNDER_ASSESSMENT → APPROVED | REFERRED | DECLINED` within one request.

`200` — approved with counter-offer
```json
{
  "decision_id": "d-4b2a...",
  "outcome": "APPROVED",
  "primary_reason_code": "INFO_AMOUNT_CAPPED",
  "reasons": [
    {"code": "INFO_AMOUNT_CAPPED", "message": "Based on your income, we can offer up to ₹16,84,000 instead of the amount you asked for."}
  ],
  "policy_version": 3,
  "offer_available": true,
  "next_step": "OFFER"
}
```
`200` — referred because of a fraud signal (applicant view)
```json
{
  "decision_id": "d-9c1e...",
  "outcome": "REFERRED",
  "reasons": [{"message": "We need to review a few details."}],
  "policy_version": 3,
  "offer_available": false,
  "next_step": "UNDER_REVIEW"
}
```
Applicant responses never include `FRAUD_*` codes. Errors: `409 INVALID_STATE_TRANSITION` (KYC or AA consent not done), `409 APPLICATION_EXPIRED`.

### `GET /applications/{id}/decision` — applicant (owner); ops/admin get the full view
Applicant view = the `assess` response. Ops/admin view adds internal detail:
```json
{
  "decision_id": "d-9c1e...",
  "outcome": "REFERRED",
  "decided_by": "engine",
  "primary_reason_code": "FRAUD_INCOME_MISMATCH",
  "reason_codes": ["FRAUD_INCOME_MISMATCH", "ELIG_EMPLOYMENT_TENURE"],
  "explanations": {
    "FRAUD_INCOME_MISMATCH": "Declared income ₹1,20,000 vs AA-verified ₹72,400 (39.7% difference > 30%).",
    "ELIG_EMPLOYMENT_TENURE": "Salaried, 4 months in current job (< 6)."
  },
  "rule_results": [
    {"rule_id": "R1", "result": "PASS"}, {"rule_id": "R2", "result": "PASS"},
    {"rule_id": "R3", "result": "PASS"}, {"rule_id": "R4", "result": "PASS", "value": 0.41},
    {"rule_id": "R5", "result": "REFER", "code": "ELIG_EMPLOYMENT_TENURE"},
    {"rule_id": "R6", "result": "PASS"},
    {"rule_id": "F2", "result": "PASS"}, {"rule_id": "F3", "result": "PASS"},
    {"rule_id": "F4", "result": "REFER", "code": "FRAUD_INCOME_MISMATCH"}
  ],
  "policy_version": 3,
  "inputs_snapshot": {
    "age_years": 31, "bureau_score": 781, "ntc": false, "existing_emis": 6000,
    "declared_income": 120000, "verified_income": 72400, "income_used": 72400,
    "income_source": "AA", "requested_amount": 800000, "tenure_months": 36,
    "applications_24h_phone": 1, "applications_24h_device": 1,
    "pan_kyc_name_similarity": 0.97, "dob_match": true
  },
  "created_at": "2026-10-20T09:06:41Z"
}
```
(Example values are illustrative only.)

### `GET /applications/{id}/offer` — applicant (owner)
```json
{
  "offer_id": "o-5e7f...",
  "status": "GENERATED",
  "policy_version": 3,
  "requested_amount": 500000,
  "loan_amount": 500000,
  "net_disbursal": 490000,
  "tenure_months": 36,
  "interest_rate": 12.99,
  "apr": 14.41,
  "emi": 16845,
  "total_interest": 106405,
  "total_fees": 10000,
  "total_repayment": 606405,
  "schedule": [
    {"month": 1, "emi": 16845, "interest": 5413, "principal": 11432, "balance": 488568}
  ],
  "cooling_off_days": 3,
  "grievance_contact": "grievance@lendwise.example",
  "assumptions": [
    "Processing fee is deducted from disbursal, not financed.",
    "EMIs are monthly in arrears.",
    "Amounts are rounded to the nearest rupee; the final EMI absorbs rounding differences.",
    "No GST, insurance or other charges are modelled."
  ],
  "disclaimer": "Simulated KFS-style disclosure for demonstration; not a legally compliant disclosure or a real offer.",
  "created_at": "2026-10-20T09:06:41Z",
  "expires_at": "2026-10-27T09:06:41Z"
}
```
(Example numbers were computed with a throwaway script using the formulas in [RULES.md §7](RULES.md) — ₹5,00,000, 36 months, 12.99%, 2% fee; schedule truncated to month 1. They will be re-checked against the engine's tests in Phase 3.) Errors: `404 NOT_FOUND` (no offer), `409 OFFER_EXPIRED`.

### `POST /applications/{id}/offer/accept` — applicant, idempotent
```json
{"kfs_acknowledged": true}
```
`200`
```json
{"offer_id": "o-5e7f...", "status": "ACCEPTED", "policy_version": 3, "next_step": "ESIGN"}
```
Errors: `400 KFS_NOT_ACKNOWLEDGED`, `409 OFFER_EXPIRED` (application moves to `EXPIRED`), `409 INVALID_STATE_TRANSITION`.

### `POST /applications/{id}/offer/esign` — applicant, idempotent *(added)*
```json
{"signature_name": "Asha Verma"}
```
`200`
```json
{"offer_id": "o-5e7f...", "status": "ESIGNED", "esign_reference": "MOCK-ESIGN-7Q2D", "next_step": "DISBURSE"}
```
Errors: `409 INVALID_STATE_TRANSITION` (offer not `ACCEPTED`), `409 OFFER_EXPIRED`.

### `POST /applications/{id}/disburse` — applicant-initiated, idempotent *(added)*
`200`
```json
{"state": "DISBURSED", "net_disbursed": 490000, "disbursal_reference": "MOCK-DISB-3K8P", "cooling_off_until": "2026-10-23T09:10:00Z"}
```
Errors: `409 INVALID_STATE_TRANSITION` (offer not `ESIGNED`).

---

## 4. Admin — policy

### `GET /admin/rules` — admin, ops, or public in read-only demo
`200`
```json
{
  "policy_version": 3,
  "rules": [
    {
      "rule_id": "R4", "kind": "ELIGIBILITY", "name": "FOIR", "enabled": true,
      "parameters": {"pass_max": 0.5, "refer_max": 0.6},
      "outcome_on_fail": "DECLINE", "reason_codes": ["ELIG_FOIR_HIGH"],
      "version": 2, "updated_by": "admin", "updated_at": "2026-10-19T12:00:00Z"
    }
  ]
}
```

### `PUT /admin/rules/{rule_id}` — admin
Creates a new policy version.
```json
{"enabled": true, "parameters": {"pass_max": 0.45, "refer_max": 0.6}, "change_comment": "Tighten FOIR pass band"}
```
`200`
```json
{"rule_id": "R4", "version": 4, "policy_version": 4, "previous_version": 2}
```
Errors: `422 POLICY_VALIDATION_ERROR` (`details.fields`), `401`, `403`.

### `GET /admin/rules/versions` — admin, ops, or public in read-only demo; paginated
Query: `rule_id` (optional), `page`, `page_size`.
```json
{
  "items": [
    {"policy_version": 4, "rule_id": "R4", "parameters": {"pass_max": 0.45, "refer_max": 0.6}, "enabled": true,
     "changed_by": "admin", "change_comment": "Tighten FOIR pass band", "created_at": "2026-10-20T10:00:00Z"},
    {"policy_version": 2, "rule_id": "R4", "parameters": {"pass_max": 0.5, "refer_max": 0.6}, "enabled": true,
     "changed_by": "admin", "change_comment": "Initial", "created_at": "2026-10-19T12:00:00Z"}
  ],
  "page": 1, "page_size": 20, "total": 2
}
```
The UI computes diffs between any two versions from these rows.

### `POST /admin/demo/reset` — admin *(added)*
Deletes applications, events, decisions, offers, reviews, OTP attempts and integration calls; restores policy to the seed version; re-registers demo persona fixtures.
`200` → `{"status": "reset", "policy_version": 1}`

### `POST /admin/jobs/expire` — admin *(added)*
Applies the 30-day abandonment and 7-day offer expiry rules.
`200` → `{"expired_abandoned": 4, "expired_offers": 1}`

---

## 5. Ops — referrals

### `GET /ops/referrals` — ops, admin, or public in read-only demo; paginated
Query: `page`, `page_size`, `reason_code` (optional filter). Ordered oldest first.
```json
{
  "items": [
    {"application_id": "a3c9...", "applicant_name": "A. V.", "pan_masked": "ZZZPZ****Q",
     "primary_reason_code": "DATA_INCOME_UNVERIFIED",
     "reason_codes": ["DATA_INCOME_UNVERIFIED", "ELIG_SCORE_BORDERLINE"],
     "income_unverified": true, "requested_amount": 400000,
     "referred_at": "2026-10-20T09:06:41Z", "hours_in_queue": 3.2}
  ],
  "page": 1, "page_size": 20, "total": 1
}
```

### `GET /ops/referrals/{id}` — ops, admin, or public in read-only demo *(added)*
Full decision (ops view above) plus application details, timeline and masked integration results:
```json
{
  "application": {"id": "a3c9...", "state": "REFERRED", "details": {}},
  "decision": {},
  "integration_results": [
    {"provider": "bureau", "status": "SUCCESS", "latency_ms": 412, "attempt": 1,
     "response_summary": {"score": 712, "existing_emis": 9000, "active_loans": 2, "max_dpd_12m": 0}}
  ],
  "timeline": []
}
```

### `POST /ops/referrals/{id}/review` — ops, admin; idempotent
```json
{"action": "APPROVE", "notes": "Salary credits stable for 6 months; borderline score acceptable."}
```
`200`
```json
{"application_id": "a3c9...", "state": "APPROVED", "review_id": "r-11ab...", "offer_id": "o-77cd...", "policy_version": 3}
```
`action` is `APPROVE` or `DECLINE`; `notes` required (min 10 characters). The offer uses the decision's `policy_version`. Errors: `422 VALIDATION_ERROR`, `409 ALREADY_REVIEWED`, `409 INVALID_STATE_TRANSITION`, `401`, `403`.

---

## 6. Metrics

### `GET /metrics/funnel` — ops, admin, or public in read-only demo
Query: `from`, `to` (ISO dates, optional).
```json
{
  "period": {"from": "2026-10-01", "to": "2026-10-20"},
  "stages": [
    {"stage": "CREATED", "count": 0},
    {"stage": "SUBMITTED", "count": 0, "drop_off_from_previous": 0.0},
    {"stage": "ASSESSED", "count": 0, "drop_off_from_previous": 0.0},
    {"stage": "APPROVED", "count": 0, "drop_off_from_previous": 0.0},
    {"stage": "DISBURSED", "count": 0, "drop_off_from_previous": 0.0}
  ],
  "conversion_application_to_disbursal": 0.0,
  "decision_mix": {"APPROVED": 0, "REFERRED": 0, "DECLINED": 0},
  "instant_decision_rate": 0.0,
  "referral_rate": 0.0,
  "fraud_flag_rate": 0.0,
  "top_reason_codes": [{"code": "ELIG_FOIR_HIGH", "count": 0}],
  "definitions": {"instant_decision_rate": "Engine APPROVED + DECLINED ÷ all engine decisions"}
}
```

### `GET /metrics/tat` — ops, admin, or public in read-only demo
```json
{
  "unit": "seconds",
  "states": [
    {"state": "DRAFT", "n_completed": 0, "median": null, "p90": null, "currently_in_state": 0},
    {"state": "KYC_PENDING", "n_completed": 0, "median": null, "p90": null, "currently_in_state": 0},
    {"state": "UNDER_ASSESSMENT", "n_completed": 0, "median": null, "p90": null, "currently_in_state": 0},
    {"state": "REFERRED", "n_completed": 0, "median": null, "p90": null, "currently_in_state": 0},
    {"state": "APPROVED", "n_completed": 0, "median": null, "p90": null, "currently_in_state": 0}
  ]
}
```

---

## 7. Mock integrations (`/mock/*`, tagged **"Mock providers (simulated)"** in Swagger)

The backend calls these mocks **in-process** through adapter interfaces; the HTTP routes expose the same mock code for inspection in Swagger. All are deterministic: behaviour comes from registered fixtures (`PUT /mock/profiles/{pan}`), then from magic PAN suffixes, then from a hash of the PAN. Latency = `MOCK_LATENCY_MS`. Every call writes an `integration_calls` row with PAN/phone masked.

**Magic PAN last letters** (override fixtures):

| Last letter | Effect |
|---|---|
| `X` | PAN status `INVALID` |
| `T` | e-KYC times out on every attempt |
| `I` | e-KYC returns `INCOMPLETE` |
| `M` | e-KYC name differs from PAN name |
| `D` | e-KYC DOB differs from PAN DOB |
| `B` | Bureau times out on every attempt |
| `N` | Bureau returns NTC (no history) |

### `POST /mock/pan/verify`
```json
{"pan": "ZZZPZ1234Q"}
```
`200` → `{"pan": "ZZZPZ****Q", "status": "VALID", "name": "ASHA VERMA", "date_of_birth": "1994-03-12"}`

### `POST /mock/kyc/start` and `POST /mock/kyc/complete`
Start: `{"pan": "ZZZPZ1234Q"}` → `{"kyc_session_id": "k-...", "status": "OTP_SENT", "demo_kyc_otp": "601245"}`
Complete: `{"kyc_session_id": "k-...", "otp": "601245"}` →
```json
{"status": "COMPLETE", "name": "ASHA VERMA", "date_of_birth": "1994-03-12", "address": {"city": "Pune", "state": "MH", "pincode": "411001"}}
```
Other statuses: `INCOMPLETE` (missing fields), or HTTP `504` with `error_code: "PROVIDER_TIMEOUT"`.

### `POST /mock/bureau/report`
```json
{"pan": "ZZZPZ1234Q"}
```
`200`
```json
{"pan": "ZZZPZ****Q", "ntc": false, "score": 742, "existing_monthly_emis": 9000, "active_loans": 2, "max_dpd_12m": 0}
```
NTC: `{"ntc": true, "score": null, "existing_monthly_emis": 0, "active_loans": 0, "max_dpd_12m": null}`. Timeout: `504 PROVIDER_TIMEOUT`.

### `POST /mock/aa/consent` and `POST /mock/aa/consent/{consent_id}/decision`
Create: `{"pan": "ZZZPZ1234Q", "purpose": "LOAN_UNDERWRITING", "months": 6}` → `{"consent_id": "aa-c-...", "status": "PENDING"}`
Decide: `{"decision": "APPROVE"}` →
```json
{
  "consent_id": "aa-c-...", "status": "APPROVED",
  "income_credits": [
    {"month": "2026-04", "amount": 84000}, {"month": "2026-05", "amount": 84000},
    {"month": "2026-06", "amount": 85200}, {"month": "2026-07", "amount": 84000},
    {"month": "2026-08", "amount": 84000}, {"month": "2026-09", "amount": 84000}
  ],
  "average_monthly_income": 84200
}
```
`{"decision": "DECLINE"}` → `{"consent_id": "aa-c-...", "status": "DECLINED"}`

### `PUT /mock/profiles/{pan}` — admin *(added)*
Registers a deterministic fixture, like a provider sandbox test identity.
```json
{
  "pan_name": "ASHA VERMA", "pan_dob": "1994-03-12", "pan_status": "VALID",
  "kyc": {"behaviour": "OK", "name": "ASHA VERMA", "dob": "1994-03-12"},
  "bureau": {"behaviour": "OK", "score": 742, "existing_monthly_emis": 9000, "active_loans": 2, "max_dpd_12m": 0},
  "aa": {"average_monthly_income": 84200}
}
```
`200` → `{"pan": "ZZZPZ****Q", "registered": true}`
