"""add heartbeat_at to test_runs

In-flight runs touch this column every ~30s so restart/crash
reconciliation can distinguish a live run (fresh heartbeat — possibly
owned by another server sharing the DB) from a dead one, instead of
guessing from started_at age.

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-06-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("test_runs", sa.Column("heartbeat_at", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_runs", "heartbeat_at")
