# Traceability Matrix (skeleton)

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.
> Status: **Phase 0 skeleton.** Endpoints and screens are planned; test names are planned and marked ⏳. Each row is marked ✅ only when the test exists and passes. Completed in Phase 7.
> Phase 1 progress: EC-01, EC-02, EC-14 and the state machine are covered by passing tests; US-01/US-02/US-09 endpoints exist (stories stay ⏳ until their screens exist).

## 1. User stories → endpoints → screens → tests

| Story | Endpoints | Screen | Planned tests | Status |
|---|---|---|---|---|
| US-01 Phone + OTP | `POST /auth/otp/send`, `POST /auth/otp/verify`, `POST /applications` | Stepper: Phone + OTP | `test_otp_send_returns_demo_code`, `test_otp_verify_issues_applicant_token`, `test_ec_01_*`, `test_ec_02_*`, `test_phone_masked_in_logs` | ⏳ |
| US-02 Details | `PATCH /applications/{id}`, `POST /applications/{id}/submit` | Stepper: Details | `test_patch_details_validates_fields`, `test_submit_moves_draft_to_kyc_pending`, `test_submit_idempotent`, `test_patch_rejected_after_submit` | ⏳ |
| US-03 PAN | `POST /applications/{id}/pan/verify`, `/mock/pan/verify` | Stepper: PAN | `test_pan_verify_logs_masked_call`, `test_ec_03_*`, `test_ec_04_*`, `test_ec_11_*`, `test_pan_invalid_status_stays_pending` | ⏳ |
| US-04 e-KYC | `POST /applications/{id}/kyc/start`, `/kyc/complete`, `/mock/kyc/*` | Stepper: e-KYC | `test_kyc_success_stores_identity`, `test_ec_05_*`, `test_ec_06_*`, `test_kyc_name_similarity_recorded` | ⏳ |
| US-05 AA consent | `POST /applications/{id}/aa/consent`, `/mock/aa/*` | Stepper: AA consent | `test_aa_approve_stores_verified_income`, `test_ec_09_*`, `test_ec_10_*` | ⏳ |
| US-06 Instant decision | `POST /applications/{id}/assess`, `GET /applications/{id}/decision`, `/mock/bureau/report` | Decision screen | `test_assess_evaluates_all_rules`, `test_applicant_view_hides_fraud_codes`, `test_ec_07_*`, `test_ec_08_*`, `test_ec_13_*`, `test_assess_idempotent` | ⏳ |
| US-07 KFS offer | `GET /applications/{id}/offer` | KFS offer screen | `test_offer_contains_kfs_fields`, `test_emi_reference_values`, `test_apr_reference_values`, `test_schedule_invariants`, `test_counter_offer_shown`, `test_accept_requires_kfs_ack` | ⏳ |
| US-08 Accept / e-sign / disburse | `POST /offer/accept`, `POST /offer/esign`, `POST /disburse` | Accept + e-sign; Disbursed | `test_offer_status_sequence`, `test_esign_requires_accepted`, `test_disburse_requires_esigned`, `test_expired_offer_moves_to_expired`, `test_ec_15_*`, Playwright `happy_path.spec.ts` | ⏳ |
| US-09 Resume | `POST /auth/otp/verify` (`resumable_applications`), `GET /applications/{id}` | Landing → resume prompt | `test_resume_returns_next_step`, `test_ec_14_*`, `test_other_phone_forbidden` | ⏳ |
| US-10 Policy editor | `GET /admin/rules`, `PUT /admin/rules/{rule_id}`, `GET /admin/rules/versions` | Admin: Policy editor | `test_rule_edit_creates_new_version`, `test_invalid_params_rejected`, `test_new_version_used_without_restart`, `test_readonly_cannot_edit` | ⏳ |
| US-11 Referral queue | `GET /ops/referrals`, `GET /ops/referrals/{id}`, `POST /ops/referrals/{id}/review` | Ops: Referral queue + detail | `test_referrals_paginated_oldest_first`, `test_referral_detail_shows_integrations`, `test_review_approve_generates_offer`, `test_review_idempotent_and_single`, `test_review_requires_ops_role` | ⏳ |
| US-12 Metrics | `GET /metrics/funnel`, `GET /metrics/tat` | PM: Metrics dashboard | `test_funnel_counts`, `test_drop_off`, `test_tat_median_p90_from_events`, `test_decision_rates` | ⏳ |

## 2. Edge cases → handling → tests

| Edge case | Handling location (planned) | Test | Status |
|---|---|---|---|
| EC-01 | `services/otp.py` | `test_ec_01_otp_locked_after_three_wrong_attempts` | ✅ |
| EC-02 | `services/otp.py` | `test_ec_02_expired_otp_rejected_and_resend_capped` | ✅ |
| EC-03 | `schemas/pan.py`, frontend PAN field | `test_ec_03_invalid_pan_format_makes_no_provider_call` | ⏳ |
| EC-04 | `services/pan.py` | `test_ec_04_pan_name_mismatch_requires_confirmation_and_feeds_f3` | ⏳ |
| EC-05 | `integrations/retry.py`, `services/kyc.py` | `test_ec_05_kyc_timeout_retries_then_stays_pending` | ⏳ |
| EC-06 | `services/kyc.py` | `test_ec_06_kyc_incomplete_asks_retry` | ⏳ |
| EC-07 | `engine/decision.py` (validate step) | `test_ec_07_bureau_timeout_refers_with_sys_code` | ⏳ |
| EC-08 | `engine/rules/r2_credit_score.py` | `test_ec_08_ntc_refers_not_declines` | ⏳ |
| EC-09 | `engine/decision.py` (resolve inputs) | `test_ec_09_aa_declined_caps_at_referred` | ⏳ |
| EC-10 | `engine/fraud/f4_income.py`, resolve inputs | `test_ec_10_income_mismatch_uses_verified_and_flags_f4` | ⏳ |
| EC-11 | `engine/fraud/f1_duplicate_pan.py`, `services/pan.py` | `test_ec_11_duplicate_pan_blocked_with_409` | ⏳ |
| EC-12 | `engine/fraud/f2_velocity.py` | `test_ec_12_velocity_flags_fourth_application` | ⏳ |
| EC-13 | `engine/rules/r1_age.py` | `test_ec_13_age_out_of_range_declines` | ⏳ |
| EC-14 | `services/expiry.py` | `test_ec_14_abandoned_application_expires_after_30_days` | ✅ |
| EC-15 | `services/offers.py`, `engine/policy.py` | `test_ec_15_acceptance_honours_decision_time_policy` | ⏳ |

## 3. Rules and fraud checks → tests

| ID | Code (planned) | Tests (planned) | Status |
|---|---|---|---|
| R1 Age | `engine/rules/r1_age.py` | boundary: day before/on 21st birthday; maturity on/after 60th birthday | ⏳ |
| R2 Credit score | `engine/rules/r2_credit_score.py` | at/below approve threshold; at/below refer floor; NTC | ⏳ |
| R3 Income | `engine/rules/r3_income.py` | ₹24,999 / ₹25,000; verified vs declared source | ⏳ |
| R4 FOIR | `engine/rules/r4_foir.py` | 0.50 / 0.5001 / 0.60 / 0.6001 | ⏳ |
| R5 Employment | `engine/rules/r5_employment.py` | 5/6 months salaried; 23/24 months self-employed | ⏳ |
| R6 LTI cap | `engine/rules/r6_lti.py` | at cap; above cap → counter-offer passes R4; above cap → R4 still fails | ⏳ |
| F1 Duplicate PAN | `engine/fraud/f1_duplicate_pan.py` | active duplicate blocked; terminal duplicate allowed | ⏳ |
| F2 Velocity | `engine/fraud/f2_velocity.py` | 3rd passes, 4th flagged; by phone; by device; outside 24h | ⏳ |
| F3 Identity | `engine/fraud/f3_identity.py` | similarity 0.84 / 0.85; DOB mismatch; confirmed EC-04 mismatch | ⏳ |
| F4 Income | `engine/fraud/f4_income.py` | 30% / 30.01%; skipped when AA declined | ⏳ |
| Precedence | `engine/decision.py` | DECLINE beats REFER; REFER beats APPROVE; primary code ordering | ⏳ |
| Pricing | `engine/pricing.py`, `engine/kfs.py` | EMI/APR reference values; invariants; zero/high fee; 12/60 months | ⏳ |
| State machine | `state_machine/machine.py` | all 11 allowed + 53 rejected pairs (`tests/test_state_machine.py`) | ✅ |

## 4. Acceptance checklist mapping

To be completed in Phase 7: each item in the final acceptance checklist (prompt §13) linked to its evidence (doc section, test, report or URL).
