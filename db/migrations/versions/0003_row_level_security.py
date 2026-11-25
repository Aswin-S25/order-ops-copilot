"""row level security

Every tenant-owned table only shows and accepts rows of the tenant set for the current
transaction (ADR-0003). `tenants` is the exception: login resolves a slug to an id there
before any tenant is known (OD-1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose: a migration must not import the models, which keep changing.
# A table added later gets its policy in its own migration (a test enforces it).
TENANT_TABLES = (
    "users",
    "orders",
    "order_items",
    "shipments",
    "shipment_events",
    "refunds",
    "conversations",
    "messages",
    "agent_runs",
    "agent_steps",
    "approvals",
    "approval_audit",
    "audit_log",
    "memories",
)

# Fails closed: with no tenant set the comparison is NULL, so no row matches and every
# write fails WITH CHECK. NULLIF because once a transaction on this connection has set the
# value, later reads of it return '' (not NULL), and ''::uuid would raise an error.
SAME_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: the table owner (app_owner) is filtered too. Only superusers bypass it.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table}"
            f" USING ({SAME_TENANT}) WITH CHECK ({SAME_TENANT})"
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
