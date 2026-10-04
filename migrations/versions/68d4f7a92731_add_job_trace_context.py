from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "68d4f7a92731"
down_revision: str | Sequence[str] | None = "f21c67a4d092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_jobs", sa.Column("traceparent", sa.String(length=55), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("run_jobs", "traceparent")
