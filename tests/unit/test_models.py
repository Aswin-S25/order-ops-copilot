"""Structural tests: the schema's safety rules are checked by code, not by memory."""

import pytest
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKeyConstraint, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable

from db import models  # noqa: F401  (registers every model on Base.metadata)
from db.base import Base

TABLES = list(Base.metadata.sorted_tables)
TENANT_OWNED = [t for t in TABLES if t.name != "tenants"]
POSTGRES_MAX_IDENTIFIER = 63


EXPECTED_TABLES = {
    "tenants",
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
}


def test_exactly_the_expected_tables_are_registered() -> None:
    # Exact match: a new table must be added here deliberately, which forces a
    # look at whether it needs tenant_id, RLS and composite FKs like the rest.
    assert {t.name for t in TABLES} == EXPECTED_TABLES


@pytest.mark.parametrize("table", TENANT_OWNED, ids=lambda t: t.name)
def test_every_table_has_non_null_tenant_fk(table: Table) -> None:
    tenant_id = table.c.get("tenant_id")
    assert tenant_id is not None, f"{table.name} has no tenant_id (RLS needs it)"
    assert not tenant_id.nullable
    # tenant_id also takes part in composite FKs (users, orders...), so check membership.
    assert "tenants" in {fk.column.table.name for fk in tenant_id.foreign_keys}


@pytest.mark.parametrize("table", TENANT_OWNED, ids=lambda t: t.name)
def test_references_between_tenant_tables_include_tenant_id(table: Table) -> None:
    # A single-column FK (e.g. order_id -> orders.id) would let a row in tenant A
    # point at a row in tenant B. Every such FK must be composite with tenant_id.
    for fk in table.foreign_key_constraints:
        assert isinstance(fk, ForeignKeyConstraint)
        if fk.referred_table.name == "tenants":
            continue
        assert "tenant_id" in fk.column_keys, f"{fk.name} on {table.name} omits tenant_id"


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_money_columns_are_bigint_with_currency(table: Table) -> None:
    money = [c for c in table.columns if c.name.endswith("_minor")]
    for column in money:
        assert isinstance(column.type, BigInteger), f"{table.name}.{column.name} must be BIGINT"
    if money:
        assert "currency" in table.c, f"{table.name} stores money without a currency"


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_all_timestamps_are_timezone_aware(table: Table) -> None:
    for column in table.columns:
        if isinstance(column.type, DateTime):
            assert column.type.timezone, f"{table.name}.{column.name} is a naive timestamp"


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_ddl_compiles_and_names_fit_postgres(table: Table) -> None:
    dialect = postgresql.dialect()
    CreateTable(table).compile(dialect=dialect)  # raises on any naming/DDL error
    for index in table.indexes:
        CreateIndex(index).compile(dialect=dialect)
    names = [c.name for c in table.constraints] + [i.name for i in table.indexes]
    for name in names:
        assert name, f"unnamed constraint/index on {table.name}"
        assert len(str(name)) <= POSTGRES_MAX_IDENTIFIER, f"{name} exceeds 63 chars"


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_json_columns_are_jsonb(table: Table) -> None:
    for column in table.columns:
        if isinstance(column.type, JSON):
            assert isinstance(column.type, JSONB), f"{table.name}.{column.name} is JSON, not JSONB"


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_foreign_key_column_types_match(table: Table) -> None:
    # Postgres refuses an FK whose two sides differ in type, but only at CREATE TABLE time.
    # This catches it at unit-test speed instead of at the first migration.
    dialect = postgresql.dialect()
    for fk in table.foreign_keys:
        local = fk.parent.type.compile(dialect=dialect)
        remote = fk.column.type.compile(dialect=dialect)
        assert local == remote, f"{table.name}.{fk.parent.name} is {local}, references {remote}"
