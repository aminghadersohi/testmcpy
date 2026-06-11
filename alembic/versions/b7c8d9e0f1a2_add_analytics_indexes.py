"""add analytics indexes for per-test x per-config aggregation

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # if_not_exists: DBs created via Base.metadata.create_all already
    # carry these indexes from the model __table_args__
    op.create_index(
        "idx_runs_suite_config",
        "test_runs",
        ["test_id", "model", "provider", "mcp_profile_id", "started_at"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_question_results_question_run",
        "question_results",
        ["question_id", "run_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_question_results_question_run", table_name="question_results")
    op.drop_index("idx_runs_suite_config", table_name="test_runs")
