"""runtime role privileges

The init script's default privileges give app_user SELECT, INSERT, UPDATE and DELETE on
every table app_owner creates. That is too much for history and for the version table.

Revision ID: 0002
Revises: 0001
Create Date: (keep the date Alembic wrote)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # History is written once: the runtime may add audit entries, never change or remove them.
    op.execute("REVOKE UPDATE, DELETE ON approval_audit, audit_log FROM app_user")
    # The runtime must not be able to make the database misreport its schema version.
    op.execute("REVOKE ALL ON alembic_version FROM app_user")


def downgrade() -> None:
    # The exact inverse, in reverse order.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version TO app_user")
    op.execute("GRANT UPDATE, DELETE ON approval_audit, audit_log TO app_user")
