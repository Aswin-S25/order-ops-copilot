"""ORM models. See docs/data-model.md for the full design.

Conventions enforced here and by tests/unit/test_models.py:
- Every table except `tenants` has tenant_id (RLS key, ADR-0003).
- A reference between two tenant-owned tables is a COMPOSITE foreign key that
  includes tenant_id, so the database itself refuses cross-tenant links.
- Money is amount_minor BIGINT + currency CHAR(3) (ADR-0012).
- No ORM relationship() yet: services use explicit queries. In async SQLAlchemy an
  implicit lazy load raises, so relationships are added only when a service needs one.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, created_at, str_enum, tenant_fk, updated_at, uuid_pk

CURRENCY_FORMAT = "currency ~ '^[A-Z]{3}$'"  # ISO 4217 code, e.g. INR
SHA256_HEX = "^[0-9a-f]{64}$"
EMBEDDING_DIMENSIONS = 1536


class UserRole(StrEnum):
    BUYER = "buyer"
    SUPPORT = "support"


class OrderStatus(StrEnum):
    PLACED = "placed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    LABEL_CREATED = "label_created"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    LOST = "lost"
    RETURNED = "returned"


class RefundReason(StrEnum):
    NOT_DELIVERED = "not_delivered"
    DAMAGED = "damaged"
    WRONG_ITEM = "wrong_item"
    OTHER = "other"


class RefundStatus(StrEnum):
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    NOTICE = "notice"


class RunRoute(StrEnum):
    FAST = "fast"
    AGENT = "agent"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StopReason(StrEnum):
    FINAL_ANSWER = "final_answer"
    MAX_ITERATIONS = "max_iterations"
    TOKEN_BUDGET = "token_budget"  # noqa: S105 (a stop reason, not a credential)
    COST_BUDGET = "cost_budget"
    DEADLINE = "deadline"
    DUPLICATE_CALLS = "duplicate_calls"
    CANCELLED = "cancelled"
    ERROR = "error"


class StepKind(StrEnum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ApprovalAction(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"


# --------------------------------------------------------------------------- identity


class Tenant(Base):
    """A marketplace operator. The only table without tenant_id and without RLS (OD-1)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{2,62}$'", name="slug_format"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))
    display_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        # Emails are stored lower-cased, so a plain unique constraint is case-insensitive.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        # Target for composite FKs from other tables: (tenant_id, id) must match a real user.
        UniqueConstraint("tenant_id", "id"),
    )


# --------------------------------------------------------------------------- commerce


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    order_number: Mapped[str] = mapped_column(String(32))
    buyer_id: Mapped[uuid.UUID]
    seller_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "order_status"))
    currency: Mapped[str] = mapped_column(String(3))
    total_minor: Mapped[int] = mapped_column(BigInteger)
    buyer_note: Mapped[str | None] = mapped_column(Text)  # UNTRUSTED: buyer-written text
    placed_at: Mapped[datetime]
    delivered_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        UniqueConstraint("tenant_id", "order_number"),
        UniqueConstraint("tenant_id", "id"),  # FK target: same tenant
        UniqueConstraint("tenant_id", "id", "currency"),  # FK target: same tenant AND currency
        ForeignKeyConstraint(["tenant_id", "buyer_id"], ["users.tenant_id", "users.id"]),
        # list_recent_orders: WHERE tenant_id AND buyer_id ORDER BY placed_at DESC
        # (a B-tree index can be scanned backwards, so no DESC needed).
        Index(None, "tenant_id", "buyer_id", "placed_at"),
        CheckConstraint("total_minor >= 0", name="total_minor_non_negative"),
        CheckConstraint(CURRENCY_FORMAT, name="currency_format"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    order_id: Mapped[uuid.UUID]
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[int]
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))

    __table_args__ = (
        # Same tenant AND same currency as the parent order, enforced by the database.
        ForeignKeyConstraint(
            ["tenant_id", "order_id", "currency"],
            ["orders.tenant_id", "orders.id", "orders.currency"],
            ondelete="CASCADE",
        ),
        Index(None, "tenant_id", "order_id"),  # Postgres does not index FK columns automatically
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_minor >= 0", name="unit_price_minor_non_negative"),
        CheckConstraint(CURRENCY_FORMAT, name="currency_format"),
    )


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    order_id: Mapped[uuid.UUID]
    carrier: Mapped[str] = mapped_column(String(64))
    tracking_number: Mapped[str] = mapped_column(String(64))
    status: Mapped[ShipmentStatus] = mapped_column(str_enum(ShipmentStatus, "shipment_status"))
    eta: Mapped[datetime | None]
    last_event_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "order_id"], ["orders.tenant_id", "orders.id"]),
        UniqueConstraint("tenant_id", "id"),  # FK target for shipment_events
        Index(None, "tenant_id", "order_id"),
    )


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    shipment_id: Mapped[uuid.UUID]
    occurred_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(64))  # carrier's raw status code
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)  # UNTRUSTED: carrier-supplied text

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "shipment_id"],
            ["shipments.tenant_id", "shipments.id"],
            ondelete="CASCADE",
        ),
        Index(None, "tenant_id", "shipment_id", "occurred_at"),
    )


class Refund(Base):
    """A financial record: never cascade-deleted, and never created without an approval."""

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    order_id: Mapped[uuid.UUID]
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[RefundReason] = mapped_column(str_enum(RefundReason, "refund_reason"))
    status: Mapped[RefundStatus] = mapped_column(str_enum(RefundStatus, "refund_status"))
    idempotency_key: Mapped[str] = mapped_column(String(64))  # sha256(run_id || call_id), ADR-0008
    requested_by: Mapped[uuid.UUID]
    approval_id: Mapped[uuid.UUID]
    created_by_run_id: Mapped[uuid.UUID]
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        # Same tenant AND same currency as the order (ADR-0012).
        ForeignKeyConstraint(
            ["tenant_id", "order_id", "currency"],
            ["orders.tenant_id", "orders.id", "orders.currency"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["tenant_id", "requested_by"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(["tenant_id", "approval_id"], ["approvals.tenant_id", "approvals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_run_id"], ["agent_runs.tenant_id", "agent_runs.id"]
        ),
        # Exactly-once side effect: a retried create_refund hits this and returns the existing row.
        UniqueConstraint("tenant_id", "idempotency_key"),
        UniqueConstraint("tenant_id", "approval_id"),
        Index(None, "tenant_id", "order_id"),
        CheckConstraint("amount_minor > 0", name="amount_minor_positive"),
        CheckConstraint(CURRENCY_FORMAT, name="currency_format"),
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="idempotency_key_format"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    user_id: Mapped[uuid.UUID]
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        UniqueConstraint("tenant_id", "id"),
        Index(None, "tenant_id", "user_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    conversation_id: Mapped[uuid.UUID]
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        Index(None, "tenant_id", "conversation_id", "created_at"),
    )


class AgentRun(Base):
    """One execution: queued -> running -> (awaiting_approval -> queued -> running)* -> done."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    conversation_id: Mapped[uuid.UUID]
    # The human the run acts for. Tools get identity from here, never from LLM output (ADR-0005).
    principal_user_id: Mapped[uuid.UUID]
    route: Mapped[RunRoute | None] = mapped_column(str_enum(RunRoute, "run_route"))
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), server_default=RunStatus.QUEUED.value
    )
    stop_reason: Mapped[StopReason | None] = mapped_column(str_enum(StopReason, "stop_reason"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    # Pinned at creation: a resumed run replays with the same model and config (ADR-0006).
    config_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    # Client's Idempotency-Key header: a retried POST returns the same run.
    client_request_key: Mapped[str | None] = mapped_column(String(128))
    iteration: Mapped[int] = mapped_column(server_default="0")
    tokens_in: Mapped[int] = mapped_column(BigInteger, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost_usd_micros: Mapped[int] = mapped_column(BigInteger, server_default="0")  # USD x 1e6
    deadline_at: Mapped[datetime]
    # Lease: Redis delivers the job, Postgres decides who may execute it (ADR-0010).
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None]
    # The loop's machine state at the last step boundary (input items, budgets, pending calls).
    checkpoint: Mapped[dict[str, Any] | None]
    checkpoint_seq: Mapped[int] = mapped_column(server_default="0")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "principal_user_id"], ["users.tenant_id", "users.id"]),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "principal_user_id", "client_request_key"),
        Index(None, "tenant_id", "conversation_id", "created_at"),
        # Reconciler: find stale queued runs and expired leases (cross-tenant, OD-2).
        Index(None, "status", "lease_expires_at"),
        # "Every run finishes with an explicit stop reason", enforced by the database:
        # a terminal status has a stop_reason, a non-terminal status has none.
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (stop_reason IS NOT NULL)",
            name="stop_reason_iff_terminal",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)", name="lease_fields_together"
        ),
        CheckConstraint(
            "iteration >= 0 AND tokens_in >= 0 AND tokens_out >= 0 AND cost_usd_micros >= 0"
            " AND checkpoint_seq >= 0",
            name="counters_non_negative",
        ),
    )


class AgentStep(Base):
    """Append-only ledger of every model call and tool call in a run."""

    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    run_id: Mapped[uuid.UUID]
    seq: Mapped[int]
    kind: Mapped[StepKind] = mapped_column(str_enum(StepKind, "step_kind"))
    status: Mapped[StepStatus] = mapped_column(str_enum(StepStatus, "step_status"))
    # tool_call steps
    call_id: Mapped[str | None] = mapped_column(String(100))  # OpenAI's id, the replay join key
    tool_name: Mapped[str | None] = mapped_column(String(64))
    args: Mapped[dict[str, Any] | None]
    args_hash: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, Any] | None]
    idempotency_key: Mapped[str | None] = mapped_column(String(64))  # side-effecting tools only
    # llm_call steps: the response's output items EXACTLY as returned (ADR-0006).
    output_items: Mapped[list[dict[str, Any]] | None]
    usage: Mapped[dict[str, Any] | None]
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("run_id", "seq"),
        # One step per OpenAI call id: a resumed run cannot record the same call twice.
        UniqueConstraint("run_id", "call_id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        # Shape depends on kind: a tool step names its call and tool; an LLM step does not.
        CheckConstraint(
            "(kind = 'llm_call' AND call_id IS NULL AND tool_name IS NULL AND args IS NULL)"
            " OR (kind = 'tool_call' AND call_id IS NOT NULL AND tool_name IS NOT NULL"
            " AND args IS NOT NULL)",
            name="fields_match_kind",
        ),
        CheckConstraint(f"args_hash ~ '{SHA256_HEX}'", name="args_hash_format"),
        CheckConstraint(f"idempotency_key ~ '{SHA256_HEX}'", name="idempotency_key_format"),
    )


# --------------------------------------------------------------------------- approvals and audit


class Approval(Base):
    """Authorises ONE exact tool call: bound to run, call, tool and argument hash (ADR-0007)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    run_id: Mapped[uuid.UUID]
    step_id: Mapped[uuid.UUID]
    call_id: Mapped[str] = mapped_column(String(100))
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]]
    args_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus, "approval_status"), server_default=ApprovalStatus.PENDING.value
    )
    requested_by: Mapped[uuid.UUID]
    decided_by: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None]
    decision_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(["tenant_id", "step_id"], ["agent_steps.tenant_id", "agent_steps.id"]),
        ForeignKeyConstraint(["tenant_id", "requested_by"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(["tenant_id", "decided_by"], ["users.tenant_id", "users.id"]),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("run_id", "call_id"),  # one approval per proposed action
        Index(None, "tenant_id", "status", "created_at"),  # the support inbox
        # Maker-checker: whoever requested the action cannot approve it.
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="maker_checker"),
        # A decision has a decider and a time; pending and expired approvals have neither.
        CheckConstraint(
            "(status IN ('approved', 'rejected', 'consumed'))"
            " = (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decision_fields_match_status",
        ),
        CheckConstraint(
            "(status = 'consumed') = (consumed_at IS NOT NULL)", name="consumed_at_iff_consumed"
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint(f"args_hash ~ '{SHA256_HEX}'", name="args_hash_format"),
    )


class ApprovalAudit(Base):
    """Append-only: Step 1.6 revokes UPDATE and DELETE from the runtime role."""

    __tablename__ = "approval_audit"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    approval_id: Mapped[uuid.UUID]
    actor_id: Mapped[uuid.UUID | None]  # NULL = the system (e.g. the expiry sweeper)
    action: Mapped[ApprovalAction] = mapped_column(str_enum(ApprovalAction, "approval_action"))
    details: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "approval_id"], ["approvals.tenant_id", "approvals.id"]),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["users.tenant_id", "users.id"]),
        Index(None, "tenant_id", "approval_id", "created_at"),
    )


class AuditLog(Base):
    """Append-only, general-purpose: who did what to which object."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    actor_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None]
    details: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["users.tenant_id", "users.id"]),
        Index(None, "tenant_id", "created_at"),
    )


# --------------------------------------------------------------------------- memory


class Memory(Base):
    """User-scoped long-term memory. Data, never instructions, and never used for authorization."""

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    user_id: Mapped[uuid.UUID]
    kind: Mapped[MemoryKind] = mapped_column(str_enum(MemoryKind, "memory_kind"))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_run_id: Mapped[uuid.UUID | None]
    superseded_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "source_run_id"], ["agent_runs.tenant_id", "agent_runs.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "superseded_by"], ["memories.tenant_id", "memories.id"]),
        UniqueConstraint("tenant_id", "id"),
        # Every memory query filters by user first (cross-user isolation, Phase 6).
        Index(None, "tenant_id", "user_id"),
        # Approximate nearest-neighbour search by cosine distance.
        Index(
            None,
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Bounded size limits how much a poisoned memory can carry into future prompts.
        CheckConstraint("char_length(content) BETWEEN 1 AND 1000", name="content_length"),
    )
