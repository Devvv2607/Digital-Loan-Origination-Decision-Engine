"""Initial schema: all tables from the PRD data model plus idempotency keys.

Revision ID: 0001
Revises: (none)
Create Date: 2026-10-21 16:37:59.712020
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('applicants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('phone_hash', sa.String(length=64), nullable=False),
    sa.Column('phone_last4', sa.String(length=4), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applicants')),
    sa.UniqueConstraint('phone_hash', name=op.f('uq_applicants_phone_hash'))
    )
    op.create_table('idempotency_keys',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('endpoint', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_keys')),
    sa.UniqueConstraint('key', 'endpoint', 'scope', name='uq_idempotency_keys_key_endpoint_scope')
    )
    op.create_table('otp_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('phone_hash', sa.String(length=64), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_otp_attempts'))
    )
    op.create_index(op.f('ix_otp_attempts_phone_hash'), 'otp_attempts', ['phone_hash'], unique=False)
    op.create_table('rule_configs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('rule_id', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome_on_fail', sa.String(length=8), nullable=True),
    sa.Column('reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('change_comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rule_configs')),
    sa.UniqueConstraint('rule_id', 'version', name='uq_rule_configs_rule_version')
    )
    op.create_index(op.f('ix_rule_configs_rule_id'), 'rule_configs', ['rule_id'], unique=False)
    op.create_index(op.f('ix_rule_configs_version'), 'rule_configs', ['version'], unique=False)
    op.create_table('applications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('applicant_id', sa.Uuid(), nullable=False),
    sa.Column('state', sa.String(length=24), nullable=False),
    sa.Column('device_id', sa.String(length=128), nullable=True),
    sa.Column('full_name', sa.String(length=120), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('employment_type', sa.String(length=16), nullable=True),
    sa.Column('employer_name', sa.String(length=120), nullable=True),
    sa.Column('months_in_current_job', sa.Integer(), nullable=True),
    sa.Column('declared_monthly_income', sa.Integer(), nullable=True),
    sa.Column('loan_amount', sa.Integer(), nullable=True),
    sa.Column('tenure_months', sa.Integer(), nullable=True),
    sa.Column('purpose', sa.String(length=32), nullable=True),
    sa.Column('pan', sa.String(length=10), nullable=True),
    sa.Column('pan_status', sa.String(length=16), nullable=False),
    sa.Column('pan_name', sa.String(length=120), nullable=True),
    sa.Column('pan_dob', sa.Date(), nullable=True),
    sa.Column('pan_name_similarity', sa.Float(), nullable=True),
    sa.Column('pan_name_confirmation', sa.String(length=24), nullable=True),
    sa.Column('kyc_status', sa.String(length=16), nullable=False),
    sa.Column('kyc_session_id', sa.String(length=64), nullable=True),
    sa.Column('kyc_name', sa.String(length=120), nullable=True),
    sa.Column('kyc_dob', sa.Date(), nullable=True),
    sa.Column('kyc_address', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('aa_status', sa.String(length=16), nullable=False),
    sa.Column('aa_consent_id', sa.String(length=64), nullable=True),
    sa.Column('aa_average_monthly_income', sa.Integer(), nullable=True),
    sa.Column('aa_income_credits', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('policy_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('state_changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('DRAFT', 'KYC_PENDING', 'UNDER_ASSESSMENT', 'APPROVED', 'REFERRED', 'DECLINED', 'DISBURSED', 'EXPIRED')", name=op.f('ck_applications_state_valid')),
    sa.ForeignKeyConstraint(['applicant_id'], ['applicants.id'], name=op.f('fk_applications_applicant_id_applicants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications'))
    )
    op.create_index(op.f('ix_applications_applicant_id'), 'applications', ['applicant_id'], unique=False)
    op.create_index(op.f('ix_applications_device_id'), 'applications', ['device_id'], unique=False)
    op.create_index(op.f('ix_applications_pan'), 'applications', ['pan'], unique=False)
    op.create_index(op.f('ix_applications_state'), 'applications', ['state'], unique=False)
    op.create_table('application_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=16), nullable=False),
    sa.Column('from_state', sa.String(length=24), nullable=True),
    sa.Column('to_state', sa.String(length=24), nullable=True),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.String(length=64), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_events_application_id_applications')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_events')),
    sa.UniqueConstraint('seq', name=op.f('uq_application_events_seq'))
    )
    op.create_index('ix_application_events_app_created', 'application_events', ['application_id', 'created_at'], unique=False)
    op.create_table('decisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=8), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.String(length=64), nullable=False),
    sa.Column('primary_reason_code', sa.String(length=48), nullable=True),
    sa.Column('reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('explanations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rule_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('inputs_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome IN ('APPROVED', 'REFERRED', 'DECLINED')", name=op.f('ck_decisions_outcome_valid')),
    sa.CheckConstraint("source IN ('ENGINE', 'MANUAL')", name=op.f('ck_decisions_source_valid')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_decisions_application_id_applications')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decisions')),
    sa.UniqueConstraint('application_id', 'source', name='uq_decisions_application_source')
    )
    op.create_index(op.f('ix_decisions_application_id'), 'decisions', ['application_id'], unique=False)
    op.create_table('integration_calls',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=True),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('request', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_integration_calls_application_id_applications')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_calls'))
    )
    op.create_index(op.f('ix_integration_calls_application_id'), 'integration_calls', ['application_id'], unique=False)
    op.create_table('offers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('decision_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('requested_amount', sa.Integer(), nullable=False),
    sa.Column('loan_amount', sa.Integer(), nullable=False),
    sa.Column('tenure_months', sa.Integer(), nullable=False),
    sa.Column('interest_rate', sa.Numeric(precision=7, scale=4), nullable=False),
    sa.Column('apr', sa.Numeric(precision=7, scale=4), nullable=False),
    sa.Column('emi', sa.Integer(), nullable=False),
    sa.Column('processing_fee', sa.Integer(), nullable=False),
    sa.Column('net_disbursal', sa.Integer(), nullable=False),
    sa.Column('total_interest', sa.Integer(), nullable=False),
    sa.Column('total_repayment', sa.Integer(), nullable=False),
    sa.Column('schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cooling_off_days', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('esigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('esign_reference', sa.String(length=32), nullable=True),
    sa.Column('disbursed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disbursal_reference', sa.String(length=32), nullable=True),
    sa.CheckConstraint("status IN ('GENERATED', 'ACCEPTED', 'ESIGNED', 'EXPIRED')", name=op.f('ck_offers_status_valid')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_offers_application_id_applications')),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], name=op.f('fk_offers_decision_id_decisions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_offers')),
    sa.UniqueConstraint('application_id', name=op.f('uq_offers_application_id'))
    )
    op.create_table('referral_reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('decision_id', sa.Uuid(), nullable=False),
    sa.Column('reviewer', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=8), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("action IN ('APPROVE', 'DECLINE')", name=op.f('ck_referral_reviews_action_valid')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_referral_reviews_application_id_applications')),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], name=op.f('fk_referral_reviews_decision_id_decisions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referral_reviews')),
    sa.UniqueConstraint('application_id', name=op.f('uq_referral_reviews_application_id'))
    )


def downgrade() -> None:
    op.drop_table('referral_reviews')
    op.drop_table('offers')
    op.drop_index(op.f('ix_integration_calls_application_id'), table_name='integration_calls')
    op.drop_table('integration_calls')
    op.drop_index(op.f('ix_decisions_application_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index('ix_application_events_app_created', table_name='application_events')
    op.drop_table('application_events')
    op.drop_index(op.f('ix_applications_state'), table_name='applications')
    op.drop_index(op.f('ix_applications_pan'), table_name='applications')
    op.drop_index(op.f('ix_applications_device_id'), table_name='applications')
    op.drop_index(op.f('ix_applications_applicant_id'), table_name='applications')
    op.drop_table('applications')
    op.drop_index(op.f('ix_rule_configs_version'), table_name='rule_configs')
    op.drop_index(op.f('ix_rule_configs_rule_id'), table_name='rule_configs')
    op.drop_table('rule_configs')
    op.drop_index(op.f('ix_otp_attempts_phone_hash'), table_name='otp_attempts')
    op.drop_table('otp_attempts')
    op.drop_table('idempotency_keys')
    op.drop_table('applicants')
