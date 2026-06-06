"""add tool_call_counts and false_positive_rate to question_results

Revision ID: a1b2c3d4e5f6
Revises: 0d982111c8e0
Create Date: 2026-06-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "0d982111c8e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("question_results", sa.Column("tool_call_counts", sa.JSON(), nullable=True))
    op.add_column(
        "question_results",
        sa.Column("false_positive_rate", sa.Float(), nullable=True, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("question_results", "false_positive_rate")
    op.drop_column("question_results", "tool_call_counts")
