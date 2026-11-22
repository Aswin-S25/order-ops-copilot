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

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, created_at, str_enum, tenant_fk, updated_at, uuid_pk

CURRENCY_FORMAT = "currency ~ '^[A-Z]{3}$'"  # ISO 4217 code, e.g. INR


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
    """A financial record: never cascade-deleted. Approval and run links arrive in Step 1.5b."""

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
        # Exactly-once side effect: a retried create_refund hits this and returns the existing row.
        UniqueConstraint("tenant_id", "idempotency_key"),
        Index(None, "tenant_id", "order_id"),
        CheckConstraint("amount_minor > 0", name="amount_minor_positive"),
        CheckConstraint(CURRENCY_FORMAT, name="currency_format"),
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="idempotency_key_format"),
    )
