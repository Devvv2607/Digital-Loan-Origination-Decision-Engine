"""Mock provider fixtures table; PAN-vs-KYC name similarity (for F3); wider verification status columns.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 17:32:38.135008
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('mock_profiles',
    sa.Column('pan', sa.String(length=10), nullable=False),
    sa.Column('profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('pan', name=op.f('pk_mock_profiles'))
    )
    op.add_column('applications', sa.Column('kyc_pan_name_similarity', sa.Float(), nullable=True))
    op.alter_column('applications', 'pan_status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.String(length=32),
               existing_nullable=False)
    op.alter_column('applications', 'kyc_status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.String(length=32),
               existing_nullable=False)
    op.alter_column('applications', 'aa_status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.String(length=32),
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('applications', 'aa_status',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    op.alter_column('applications', 'kyc_status',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    op.alter_column('applications', 'pan_status',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    op.drop_column('applications', 'kyc_pan_name_similarity')
    op.drop_table('mock_profiles')
