"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-11-22 10:54:25.063692
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name=op.f("ck_tenants_slug_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "buyer",
                "support",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_users_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id_email")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_users_tenant_id_id")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_audit_log_tenant_id_actor_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_log_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        op.f("ix_audit_log_tenant_id_created_at"),
        "audit_log",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_conversations_tenant_id_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_conversations_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_conversations_tenant_id_user_id_updated_at"),
        "conversations",
        ["tenant_id", "user_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("seller_name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "placed",
                "shipped",
                "delivered",
                "cancelled",
                name="order_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("buyer_note", sa.Text(), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_orders_currency_format")),
        sa.CheckConstraint("total_minor >= 0", name=op.f("ck_orders_total_minor_non_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "buyer_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_orders_tenant_id_buyer_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_orders_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint(
            "tenant_id", "id", "currency", name=op.f("uq_orders_tenant_id_id_currency")
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_orders_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "order_number", name=op.f("uq_orders_tenant_id_order_number")
        ),
    )
    op.create_index(
        op.f("ix_orders_tenant_id_buyer_id_placed_at"),
        "orders",
        ["tenant_id", "buyer_id", "placed_at"],
        unique=False,
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("principal_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "route",
            sa.Enum(
                "fast",
                "agent",
                name="run_route",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "awaiting_approval",
                "completed",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "stop_reason",
            sa.Enum(
                "final_answer",
                "max_iterations",
                "token_budget",
                "cost_budget",
                "deadline",
                "duplicate_calls",
                "cancelled",
                "error",
                name="stop_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("client_request_key", sa.String(length=128), nullable=True),
        sa.Column("iteration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cost_usd_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checkpoint_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (stop_reason IS NOT NULL)",
            name=op.f("ck_agent_runs_stop_reason_iff_terminal"),
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name=op.f("ck_agent_runs_lease_fields_together"),
        ),
        sa.CheckConstraint(
            "iteration >= 0 AND tokens_in >= 0 AND tokens_out >= 0 AND cost_usd_micros >= 0 AND checkpoint_seq >= 0",
            name=op.f("ck_agent_runs_counters_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_agent_runs_tenant_id_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_agent_runs_tenant_id_principal_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agent_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_agent_runs_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "principal_user_id",
            "client_request_key",
            name=op.f("uq_agent_runs_tenant_id_principal_user_id_client_request_key"),
        ),
    )
    op.create_index(
        op.f("ix_agent_runs_status_lease_expires_at"),
        "agent_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_runs_tenant_id_conversation_id_created_at"),
        "agent_runs",
        ["tenant_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_order_items_currency_format")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_price_minor >= 0", name=op.f("ck_order_items_unit_price_minor_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id", "currency"],
            ["orders.tenant_id", "orders.id", "orders.currency"],
            name=op.f("fk_order_items_tenant_id_order_id_currency_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_order_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
    )
    op.create_index(
        op.f("ix_order_items_tenant_id_order_id"),
        "order_items",
        ["tenant_id", "order_id"],
        unique=False,
    )
    op.create_table(
        "shipments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("tracking_number", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "label_created",
                "in_transit",
                "out_for_delivery",
                "delivered",
                "lost",
                "returned",
                name="shipment_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
            name=op.f("fk_shipments_tenant_id_order_id_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_shipments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipments")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_shipments_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_shipments_tenant_id_order_id"),
        "shipments",
        ["tenant_id", "order_id"],
        unique=False,
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "llm_call",
                "tool_call",
                name="step_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "awaiting_approval",
                "succeeded",
                "failed",
                "skipped",
                name="step_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("call_id", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("args_hash", sa.String(length=64), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("output_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'llm_call' AND call_id IS NULL AND tool_name IS NULL AND args IS NULL) OR (kind = 'tool_call' AND call_id IS NOT NULL AND tool_name IS NOT NULL AND args IS NOT NULL)",
            name=op.f("ck_agent_steps_fields_match_kind"),
        ),
        sa.CheckConstraint(
            "args_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_agent_steps_args_hash_format")
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'", name=op.f("ck_agent_steps_idempotency_key_format")
        ),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_agent_steps_seq_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_agent_steps_tenant_id_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agent_steps_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
        sa.UniqueConstraint("run_id", "call_id", name=op.f("uq_agent_steps_run_id_call_id")),
        sa.UniqueConstraint("run_id", "seq", name=op.f("uq_agent_steps_run_id_seq")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_agent_steps_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name=op.f("uq_agent_steps_tenant_id_idempotency_key")
        ),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "preference",
                "fact",
                name="memory_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 1000", name=op.f("ck_memories_content_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_memories_tenant_id_source_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "superseded_by"],
            ["memories.tenant_id", "memories.id"],
            name=op.f("fk_memories_tenant_id_superseded_by_memories"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_memories_tenant_id_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_memories_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_memories_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_memories_embedding"),
        "memories",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_memories_tenant_id_user_id"), "memories", ["tenant_id", "user_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                "notice",
                name="message_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_messages_tenant_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_messages_tenant_id_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_messages_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        op.f("ix_messages_tenant_id_conversation_id_created_at"),
        "messages",
        ["tenant_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "shipment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("shipment_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shipment_id"],
            ["shipments.tenant_id", "shipments.id"],
            name=op.f("fk_shipment_events_tenant_id_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_shipment_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_events")),
    )
    op.create_index(
        op.f("ix_shipment_events_tenant_id_shipment_id_occurred_at"),
        "shipment_events",
        ["tenant_id", "shipment_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "expired",
                "consumed",
                name="approval_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'consumed') = (consumed_at IS NOT NULL)",
            name=op.f("ck_approvals_consumed_at_iff_consumed"),
        ),
        sa.CheckConstraint(
            "(status IN ('approved', 'rejected', 'consumed')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name=op.f("ck_approvals_decision_fields_match_status"),
        ),
        sa.CheckConstraint(
            "args_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_approvals_args_hash_format")
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> requested_by",
            name=op.f("ck_approvals_maker_checker"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_approvals_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_approvals_tenant_id_decided_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_approvals_tenant_id_requested_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_approvals_tenant_id_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "step_id"],
            ["agent_steps.tenant_id", "agent_steps.id"],
            name=op.f("fk_approvals_tenant_id_step_id_agent_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_approvals_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint("run_id", "call_id", name=op.f("uq_approvals_run_id_call_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_approvals_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_approvals_tenant_id_status_created_at"),
        "approvals",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "approval_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "requested",
                "approved",
                "rejected",
                "expired",
                "consumed",
                name="approval_action",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_approval_audit_tenant_id_actor_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["approvals.tenant_id", "approvals.id"],
            name=op.f("fk_approval_audit_tenant_id_approval_id_approvals"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_approval_audit_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_audit")),
    )
    op.create_index(
        op.f("ix_approval_audit_tenant_id_approval_id_created_at"),
        "approval_audit",
        ["tenant_id", "approval_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "not_delivered",
                "damaged",
                "wrong_item",
                "other",
                name="refund_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "succeeded",
                "failed",
                name="refund_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("provider_ref", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_refunds_currency_format")),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'", name=op.f("ck_refunds_idempotency_key_format")
        ),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_refunds_amount_minor_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["approvals.tenant_id", "approvals.id"],
            name=op.f("fk_refunds_tenant_id_approval_id_approvals"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_refunds_tenant_id_created_by_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id", "currency"],
            ["orders.tenant_id", "orders.id", "orders.currency"],
            name=op.f("fk_refunds_tenant_id_order_id_currency_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_refunds_tenant_id_requested_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_refunds_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refunds")),
        sa.UniqueConstraint(
            "tenant_id", "approval_id", name=op.f("uq_refunds_tenant_id_approval_id")
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name=op.f("uq_refunds_tenant_id_idempotency_key")
        ),
    )
    op.create_index(
        op.f("ix_refunds_tenant_id_order_id"), "refunds", ["tenant_id", "order_id"], unique=False
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_refunds_tenant_id_order_id"), table_name="refunds")
    op.drop_table("refunds")
    op.drop_index(
        op.f("ix_approval_audit_tenant_id_approval_id_created_at"), table_name="approval_audit"
    )
    op.drop_table("approval_audit")
    op.drop_index(op.f("ix_approvals_tenant_id_status_created_at"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(
        op.f("ix_shipment_events_tenant_id_shipment_id_occurred_at"), table_name="shipment_events"
    )
    op.drop_table("shipment_events")
    op.drop_index(op.f("ix_messages_tenant_id_conversation_id_created_at"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_memories_tenant_id_user_id"), table_name="memories")
    op.drop_index(
        op.f("ix_memories_embedding"),
        table_name="memories",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("memories")
    op.drop_table("agent_steps")
    op.drop_index(op.f("ix_shipments_tenant_id_order_id"), table_name="shipments")
    op.drop_table("shipments")
    op.drop_index(op.f("ix_order_items_tenant_id_order_id"), table_name="order_items")
    op.drop_table("order_items")
    op.drop_index(
        op.f("ix_agent_runs_tenant_id_conversation_id_created_at"), table_name="agent_runs"
    )
    op.drop_index(op.f("ix_agent_runs_status_lease_expires_at"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(op.f("ix_orders_tenant_id_buyer_id_placed_at"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_conversations_tenant_id_user_id_updated_at"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_audit_log_tenant_id_created_at"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("tenants")
    # ### end Alembic commands ###
