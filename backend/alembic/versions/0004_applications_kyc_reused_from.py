"""Record when an application reuses e-KYC completed on the same applicant's earlier application (D-47).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('kyc_reused_from_application_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_applications_kyc_reused_from_application_id_applications', 'applications',
                          'applications', ['kyc_reused_from_application_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_applications_kyc_reused_from_application_id_applications', 'applications',
                       type_='foreignkey')
    op.drop_column('applications', 'kyc_reused_from_application_id')
