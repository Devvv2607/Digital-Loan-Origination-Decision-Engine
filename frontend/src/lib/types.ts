/** Response shapes from the backend (see docs/API.md). */

export type AppState =
  | "DRAFT"
  | "KYC_PENDING"
  | "UNDER_ASSESSMENT"
  | "APPROVED"
  | "REFERRED"
  | "DECLINED"
  | "DISBURSED"
  | "EXPIRED";

export type NextStep =
  | "DETAILS"
  | "SUBMIT"
  | "PAN"
  | "EKYC"
  | "AA_CONSENT"
  | "ASSESS"
  | "OFFER"
  | "ESIGN"
  | "DISBURSE"
  | "UNDER_REVIEW"
  | "DECISION"
  | "DONE"
  | "START_NEW";

export interface Details {
  full_name: string | null;
  date_of_birth: string | null;
  employment_type: "SALARIED" | "SELF_EMPLOYED" | null;
  employer_name: string | null;
  months_in_current_job: number | null;
  declared_monthly_income: number | null;
  loan_amount: number | null;
  tenure_months: number | null;
  purpose: string | null;
}

export interface ApplicationView {
  id: string;
  state: AppState;
  next_step: NextStep;
  details: Details;
  pan: { masked: string | null; status: string };
  /** `reused`: e-KYC was reused from an earlier application with the same PAN (D-47). */
  kyc: { status: string; reused: boolean };
  aa: { status: string };
  policy_version: number | null;
  created_at: string;
  last_activity_at: string;
}

export interface MyApplication {
  id: string;
  state: AppState;
  next_step: NextStep;
  loan_amount: number | null;
  tenure_months: number | null;
  purpose: string | null;
  kyc_reused: boolean;
  created_at: string;
  last_activity_at: string;
}

export interface MyApplications {
  items: MyApplication[];
  kyc_on_file: boolean;
}

export interface Persona {
  persona_id: string;
  label: string;
  description: string;
  expected_outcome: string;
  phone: string;
  pan: string;
  details: Omit<Details, "employment_type"> & { employment_type: "SALARIED" | "SELF_EMPLOYED" };
  aa_decision: "APPROVE" | "DECLINE";
}

export interface DecisionView {
  decision_id: string;
  outcome: "APPROVED" | "REFERRED" | "DECLINED";
  decided_by: "engine" | "analyst";
  primary_reason_code: string | null;
  reasons: { code: string | null; message: string }[];
  policy_version: number;
  offer_available: boolean;
  next_step: NextStep;
  created_at: string;
}

export interface ScheduleRow {
  month: number;
  emi: number;
  interest: number;
  principal: number;
  balance: number;
}

export interface Offer {
  offer_id: string;
  status: "GENERATED" | "ACCEPTED" | "ESIGNED" | "EXPIRED";
  policy_version: number;
  requested_amount: number;
  loan_amount: number;
  amount_capped: boolean;
  net_disbursal: number;
  tenure_months: number;
  interest_rate: number;
  apr: number;
  emi: number;
  total_interest: number;
  total_fees: number;
  total_cost: number;
  total_repayment: number;
  schedule: ScheduleRow[];
  cooling_off_days: number;
  grievance_contact: string;
  assumptions: string[];
  disclaimer: string;
  created_at: string;
  expires_at: string;
  esign_reference: string | null;
  disbursal_reference: string | null;
  disbursed_at: string | null;
  application_state: AppState;
  next_step: NextStep;
}

export interface OfferActionResult {
  offer_id: string;
  status: Offer["status"];
  policy_version: number;
  application_state: AppState;
  esign_reference: string | null;
  disbursal_reference: string | null;
  net_disbursed: number | null;
  cooling_off_days: number;
  next_step: NextStep;
}
