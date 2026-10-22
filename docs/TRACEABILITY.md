# Traceability Matrix

> Demo prototype. Simulated integrations and synthetic data. Not affiliated with any bank or lender.
> Status: **Phase 7, complete.** Every row names tests that exist and pass (404 backend tests, 98% coverage; Playwright happy path and cold-start notice; 500/500 simulation). Backend test files are under `backend/tests/`; screens under `frontend/src/`. "UI check" says how the screen itself was verified: the Playwright test (`frontend/tests/e2e/happy-path.spec.ts`), or manual desktop and 390 px phone screenshots taken during Phases 4-7.

## 1. User stories → endpoints → screens → tests

| Story | Endpoints | Screen | Tests | UI check | Status |
|---|---|---|---|---|---|
| US-01 Phone + OTP | `POST /auth/otp/send`, `POST /auth/otp/verify`, `POST /applications` | `components/apply/steps/phone-step.tsx` | `test_otp.py`: `test_send_returns_simulated_code_valid_for_five_minutes`, `test_verify_issues_applicant_token_and_reuses_applicant`, `test_code_cannot_be_reused`, `test_ec_01_otp_locked_after_three_wrong_attempts`, `test_ec_02_expired_otp_rejected_and_resend_capped`, `test_phone_never_logged_in_clear`; `test_applications.py`: `test_create_starts_in_draft_with_creation_event` | Playwright | ✅ |
| US-02 Details | `PATCH /applications/{application_id}`, `POST /applications/{application_id}/submit` | `steps/details-step.tsx` | `test_applications.py`: `test_details_can_be_saved_in_steps`, `test_invalid_details_rejected_field_by_field`, `test_future_date_of_birth_rejected`, `test_submit_requires_all_details`, `test_submit_moves_draft_to_kyc_pending`, `test_submit_idempotency_key_replays_original_response`, `test_details_locked_after_submit` | Playwright | ✅ |
| US-03 PAN | `POST /applications/{application_id}/pan/verify`, `POST /mock/pan/verify` | `steps/pan-step.tsx` | `test_verification.py`: `test_pan_verified_when_names_match`, `test_ec_03_invalid_pan_format_makes_no_provider_call`, `test_ec_04_pan_name_mismatch_requires_confirmation_and_feeds_f3`, `test_ec_11_duplicate_pan_blocked_with_409`, `test_pan_reported_invalid_by_provider`; `test_mock_api.py`: `test_mock_pan_masks_pan_and_logs` | Playwright | ✅ |
| US-04 e-KYC | `POST /applications/{application_id}/kyc/start`, `/kyc/complete`, `/mock/kyc/*` | `steps/ekyc-step.tsx` | `test_verification.py`: `test_kyc_success_stores_identity_and_similarity`, `test_ec_05_kyc_timeout_retries_then_stays_pending`, `test_ec_06_kyc_incomplete_asks_retry`, `test_kyc_identity_mismatch_recorded_for_f3`, `test_kyc_wrong_otp` | Playwright | ✅ |
| US-05 AA consent | `POST /applications/{application_id}/aa/consent`, `/mock/aa/*` | `steps/consent-step.tsx` | `test_verification.py`: `test_aa_approve_stores_verified_income`, `test_aa_decline_records_choice_and_moves_on`; `test_assessment.py`: `test_ec_09_aa_declined_caps_at_referred`, `test_ec_10_income_mismatch_uses_verified_and_flags_f4` | Playwright | ✅ |
| US-06 Instant decision | `POST /applications/{application_id}/assess`, `GET /applications/{application_id}/decision`, `POST /mock/bureau/report` | `steps/assess-step.tsx`, `steps/decision-step.tsx` | `test_assessment.py`: `test_strong_applicant_approved_instantly_with_offer`, `test_assess_is_idempotent_with_and_without_key`, `test_ec_07_bureau_timeout_refers_with_sys_code`, `test_ec_08_ntc_refers_not_declines`, `test_ec_13_age_out_of_range_declines`, `test_decision_access_control`; `test_rules_and_checks.py`: `test_fraud_wording_never_reveals_the_check`; `test_decision_engine.py`: `test_reason_codes_complete_for_outcome` | Playwright (approval); manual (refer, decline) | ✅ |
| US-07 KFS offer | `GET /applications/{application_id}/offer` | `steps/offer-stage.tsx` | `test_offers.py`: `test_kfs_offer_shows_every_required_field`, `test_counter_offer_is_shown_against_requested_amount`, `test_accept_requires_kfs_acknowledgement`; `test_pricing.py`: `test_emi_matches_reference`, `test_apr_matches_independent_reference`, `test_kfs_consistency_invariants` | Playwright (KFS figures, tick required) | ✅ |
| US-08 Accept / e-sign / disburse | `POST /offer/accept`, `POST /offer/esign`, `POST /disburse` | `steps/offer-stage.tsx` | `test_offers.py`: `test_accept_esign_disburse_are_separate_ordered_steps`, `test_offer_steps_are_idempotent`, `test_expired_offer_cannot_be_accepted`, `test_ec_15_acceptance_honours_decision_time_policy`; `test_expiry.py`: `test_unsigned_offer_expires_after_7_days_lazily`; `test_state_machine.py`: `test_offer_status_transitions` | Playwright (to disbursal) | ✅ |
| US-09 Resume | `POST /auth/otp/verify` (`resumable_applications`), `GET /applications/{application_id}` | `components/apply/flow.tsx` (resume prompt) | `test_applications.py`: `test_resumable_applications_returned_at_login`, `test_other_applicant_cannot_read_application`; `test_expiry.py`: `test_ec_14_abandoned_application_expires_after_30_days`, `test_ec_14_expired_applications_are_not_offered_for_resume` | manual | ✅ |
| US-10 Policy editor | `GET /admin/rules`, `PUT /admin/rules/{rule_id}`, `GET /admin/rules/versions` | `/internal/policy` (`components/internal/policy-editor.tsx`) | `test_policy.py`: `test_edit_creates_new_version_and_old_version_is_reconstructable`, `test_invalid_parameters_rejected_without_new_version`, `test_admin_edit_and_version_history`, `test_edit_requires_admin`, `test_rules_are_publicly_readable_in_demo_mode`; `test_assessment.py`: `test_new_policy_version_used_without_restart` | manual (including an admin edit of R4) | ✅ |
| US-11 Referral queue | `GET /ops/referrals`, `GET /ops/referrals/{application_id}`, `POST /ops/referrals/{application_id}/review` | `/internal/referrals`, `/internal/referrals/{id}` (`components/internal/referrals.tsx`) | `test_ops.py`: `test_queue_lists_referrals_oldest_first_with_flags`, `test_detail_has_reasons_inputs_integrations_and_timeline`, `test_approve_generates_offer_under_decision_policy_version`, `test_review_is_idempotent_and_single`, `test_notes_are_mandatory`, `test_review_requires_ops_or_admin`, `test_public_read_only_view_shows_initials_only` | manual | ✅ |
| US-12 Metrics | `GET /metrics/funnel`, `GET /metrics/tat` | `/internal/metrics` (`components/internal/metrics-dashboard.tsx`) | `test_metrics.py`: `test_funnel_counts_and_drop_off`, `test_decision_rates_fraud_rate_and_reasons`, `test_date_filter`, `test_tat_from_event_log`, `test_percentile_definition`; `test_demo_seed.py`: `test_tat_is_flagged_as_simulated_timings` | manual | ✅ |

## 2. Edge cases → handling → tests

| Edge case | Handling location | Test | Status |
|---|---|---|---|
| EC-01 | `services/otp.py` | `test_ec_01_otp_locked_after_three_wrong_attempts` | ✅ |
| EC-02 | `services/otp.py` | `test_ec_02_expired_otp_rejected_and_resend_capped` | ✅ |
| EC-03 | `services/verification.py` (`verify_pan`), frontend PAN field (`steps/pan-step.tsx`) | `test_ec_03_invalid_pan_format_makes_no_provider_call` | ✅ |
| EC-04 | `services/verification.py` (`verify_pan`) | `test_ec_04_pan_name_mismatch_requires_confirmation_and_feeds_f3` | ✅ |
| EC-05 | `integrations/calls.py` (`call_with_retries`), `services/verification.py` (`complete_kyc`) | `test_ec_05_kyc_timeout_retries_then_stays_pending` | ✅ |
| EC-06 | `services/verification.py` (`complete_kyc`) | `test_ec_06_kyc_incomplete_asks_retry` | ✅ |
| EC-07 | `services/verification.py` (`fetch_bureau_report`), `engine/decision.py` (step 1) | `test_ec_07_bureau_timeout_refers_with_sys_code` | ✅ |
| EC-08 | `engine/rules.py` (`r2_credit_score`) | `test_ec_08_ntc_refers_not_declines` | ✅ |
| EC-09 | `engine/decision.py` (step 2) | `test_ec_09_aa_declined_caps_at_referred` | ✅ |
| EC-10 | `engine/fraud/checks.py` (`f4_income`), `engine/decision.py` (step 2) | `test_ec_10_income_mismatch_uses_verified_and_flags_f4` | ✅ |
| EC-11 | `engine/fraud/f1_duplicate_pan.py`, `services/verification.py` | `test_ec_11_duplicate_pan_blocked_with_409` | ✅ |
| EC-12 | `engine/fraud/checks.py` (`f2_velocity`), `services/assessment.py` (`velocity_counts`) | `test_ec_12_velocity_flags_fourth_application` | ✅ |
| EC-13 | `engine/rules.py` (`r1_age`) | `test_ec_13_age_out_of_range_declines` | ✅ |
| EC-14 | `services/expiry.py` | `test_ec_14_abandoned_application_expires_after_30_days` | ✅ |
| EC-15 | `services/offers.py`, `engine/policy.py` (versioned load) | `test_ec_15_acceptance_honours_decision_time_policy` | ✅ |

## 3. Rules and fraud checks → tests

| ID | Code | Tests (`test_rules_and_checks.py`, `test_decision_engine.py`, `test_pricing.py`, `test_state_machine.py`) | Status |
|---|---|---|---|
| R1 Age | `engine/rules.py` | boundary: day before/on 21st birthday; maturity on/after 60th birthday | ✅ |
| R2 Credit score | `engine/rules.py` | at/below approve threshold; at/below refer floor; NTC | ✅ |
| R3 Income | `engine/rules.py` | ₹24,999 / ₹25,000; verified vs declared source | ✅ |
| R4 FOIR | `engine/rules.py` | 0.50 / 0.5001 / 0.60 / 0.6001 | ✅ |
| R5 Employment | `engine/rules.py` | 5/6 months salaried; 23/24 months self-employed | ✅ |
| R6 LTI cap | `engine/rules.py, engine/decision.py` | at cap; above cap → counter-offer passes R4; above cap → R4 still fails | ✅ |
| F1 Duplicate PAN | `engine/fraud/f1_duplicate_pan.py` | active duplicate blocked; terminal duplicate allowed | ✅ |
| F2 Velocity | `engine/fraud/checks.py` | 3rd passes, 4th flagged; by phone; by device; outside 24h | ✅ |
| F3 Identity | `engine/fraud/checks.py` | similarity 0.84 / 0.85; DOB mismatch; confirmed EC-04 mismatch | ✅ |
| F4 Income | `engine/fraud/checks.py` | 30% / 30.01%; skipped when AA declined | ✅ |
| Precedence | `engine/decision.py` | DECLINE beats REFER; REFER beats APPROVE; primary code ordering | ✅ |
| Pricing | `engine/pricing.py, services/offers.py` | EMI/APR reference values; invariants; zero/high fee; 12/60 months | ✅ |
| State machine | `state_machine/machine.py` | all 11 allowed + 53 rejected pairs (`tests/test_state_machine.py`) | ✅ |

## 4. Acceptance checklist mapping (spec §13)

| Checklist item | Evidence | Status |
|---|---|---|
| PRD has exactly 12 user stories, each with acceptance criteria | `docs/PRD.md` (US-01 to US-12); §1 above | ✅ |
| Exactly 15 edge cases, each with handling code and a passing `test_ec_XX` | `docs/PRD.md`; §2 above (EC-01 to EC-15, all passing) | ✅ |
| State machine has exactly 8 states; illegal transitions rejected and tested | `docs/STATE_MACHINE.md`; `test_exactly_eight_states_and_three_terminal`, `test_illegal_transition_rejected_without_side_effects`, `test_allowed_transition_table_matches_spec`; simulation assertion "only legal transitions" | ✅ |
| 4 mock integrations, deterministic, logged, visible in Swagger | `backend/app/integrations/mock/`; `test_same_pan_gives_same_profile`, `test_logged_call_records_masked_request_and_response`, `test_all_four_mocks_are_in_swagger_under_a_mock_tag` | ✅ |
| `docs/API.md` documents every endpoint with examples | `docs/API.md`; `scripts/check_api_docs.py` (39 of 39, run in CI) | ✅ |
| Exactly 6 eligibility rules, editable from the admin UI, versioned | `docs/RULES.md`; `/internal/policy`; `test_seed_policy_has_exactly_6_rules_4_fraud_checks_and_pricing`, `test_edit_creates_new_version_and_old_version_is_reconstructable` | ✅ |
| R2 thresholds generated by `seed_policy_from_cutoff.py` from the 88.2% scenario, documented as illustrative | `docs/RULES.md` §6; `test_seed_script_calibrates_to_reference_approval_rate`, `test_committed_seed_file_is_reproducible_from_the_script` | ✅ |
| Exactly 4 fraud checks, implemented and tested | `backend/app/engine/fraud/`; `test_f2_velocity`, `test_f3_identity`, `test_f4_income`, `test_ec_11_duplicate_pan_blocked_with_409` | ✅ |
| Documented evaluation sequence; `SYS_`/`DATA_`/`FRAUD_`/`ELIG_`/`INFO_` codes distinct | `docs/RULES.md`; `test_reason_code_families_are_distinct`, `test_refer_reasons_are_ordered_by_priority` | ✅ |
| Counter-offers re-run FOIR before being offered | `test_counter_offer_reruns_foir_on_capped_amount_and_approves`, `test_counter_offer_not_made_when_capped_amount_still_unaffordable` | ✅ |
| Every decision returns outcome, reason codes and policy version | `test_strong_applicant_is_approved_with_every_check_evaluated`; simulation assertion "policy version recorded on every decision" | ✅ |
| Offer status GENERATED → ACCEPTED → ESIGNED; DISBURSED only after e-sign | `test_offer_status_transitions`, `test_accept_esign_disburse_are_separate_ordered_steps` | ✅ |
| KFS screen: APR, EMI, total cost, fees, assumptions, cooling-off; tick required; EMI/APR invariants tested | `steps/offer-stage.tsx`; Playwright test (figures, Accept disabled until ticked); `test_kfs_offer_shows_every_required_field`, `test_kfs_consistency_invariants` | ✅ |
| Admin/ops writes protected; public demo read-only; rate limits on; PAN/phone masked in logs | `test_admin_route_rejects_applicant_and_ops`, `test_edit_requires_admin`, `test_review_requires_ops_or_admin`, `test_otp_send_rate_limited_per_ip`, `test_logging_masks_pan_even_if_code_forgets`, `test_phone_never_logged_in_clear`; per-visitor limits behind the host's proxy (D-45) | ✅ |
| Idempotency on submit, assess, accept and review; `/health` works | `test_submit_idempotency_key_replays_original_response`, `test_assess_is_idempotent_with_and_without_key`, `test_offer_steps_are_idempotent`, `test_review_is_idempotent_and_single`, `test_health_ok` | ✅ |
| Exactly 500 synthetic applications through the API; report from the real run | `reports/simulation_report.md` (500/500 on the fixed as-of clock); D-43 mutation check shows the run can fail | ✅ |
| Frontend, backend and database deployed, with working public links | README "Live demo" | ⏳ needs the hosting accounts (D-45) |
| Demo banner on every page; no real lender branding | sticky banner in the root layout; the Playwright test checks it; repository history scanned for real lender names | ✅ |
| README complete, with real numbers only | `README.md` (simulation figures copied from the report) | ✅ (live links added after deploy) |
