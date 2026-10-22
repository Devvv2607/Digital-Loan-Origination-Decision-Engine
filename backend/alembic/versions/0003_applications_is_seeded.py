"""Flag applications loaded from the demo seed (their stage timings are simulated, D-44).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('is_seeded', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('applications', 'is_seeded')
