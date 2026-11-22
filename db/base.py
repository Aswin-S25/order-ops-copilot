"""Declarative base, naming convention and column helpers shared by every model."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint and index names. Alembic needs stable names to alter or
# drop them later, and they appear in IntegrityError messages, which Phase 3 maps
# to domain errors (e.g. uq_refunds_tenant_id_idempotency_key -> "already done").
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every Mapped[datetime] becomes TIMESTAMPTZ: a naive timestamp cannot be declared by accident.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def uuid_pk() -> Mapped[uuid.UUID]:
    # Generated in the application (OD-10), so the id is known before INSERT.
    return mapped_column(primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    # RLS policies (Phase 2) filter on this column. RESTRICT: never cascade-delete a tenant's data.
    return mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def updated_at() -> Mapped[datetime]:
    # onupdate fires for ORM updates only; bulk UPDATE statements must set it explicitly.
    return mapped_column(server_default=func.now(), onupdate=func.now())


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint instead of a native Postgres ENUM type.

    Native ENUMs are awkward to migrate (values cannot be removed or renamed easily);
    a CHECK constraint is replaced in one ordinary migration.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
    )
