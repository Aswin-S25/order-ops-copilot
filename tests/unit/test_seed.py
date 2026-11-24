"""The seed data's own rules, checked without a database."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from db.models import OrderStatus, UserRole
from db.seed import TENANTS, main, tenant_rows
from tests.support import make_settings

NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)


def build() -> dict[str, list[dict[str, Any]]]:
    """Every seeded row for every tenant, grouped by table name."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for slug, name in TENANTS.items():
        for model, rows in tenant_rows(slug, name, now=NOW, make_password_hash=lambda: "hash"):
            tables.setdefault(model.__tablename__, []).extend(rows)
    return tables


def test_rows_are_deterministic() -> None:
    # Same input, same ids and values: tests and evals can refer to seeded rows by id.
    assert build() == build()


def test_no_two_rows_share_an_id() -> None:
    ids = [row["id"] for rows in build().values() for row in rows]
    assert len(ids) == len(set(ids))


def test_tenants_reuse_the_same_emails_and_order_numbers() -> None:
    # Deliberate: a query that forgets the tenant filter finds two rows instead of one.
    tables = build()
    for table, column in (("users", "email"), ("orders", "order_number")):
        values = [row[column] for row in tables[table]]
        assert len(values) == len(TENANTS) * len(set(values))


def test_every_order_belongs_to_a_buyer_in_its_own_tenant() -> None:
    # The composite FK guarantees the tenant; only this test guarantees the role.
    tables = build()
    buyers = {(u["tenant_id"], u["id"]) for u in tables["users"] if u["role"] == UserRole.BUYER}
    for order in tables["orders"]:
        assert (order["tenant_id"], order["buyer_id"]) in buyers


def test_delivered_at_is_set_exactly_for_delivered_orders() -> None:
    for order in build()["orders"]:
        assert (order["status"] == OrderStatus.DELIVERED) == (order["delivered_at"] is not None)


def test_shipment_last_event_at_is_its_latest_event() -> None:
    tables = build()
    for shipment in tables["shipments"]:
        times = [
            event["occurred_at"]
            for event in tables["shipment_events"]
            if event["shipment_id"] == shipment["id"]
        ]
        assert shipment["last_event_at"] == max(times, default=None)


def test_refuses_to_seed_production_before_connecting() -> None:
    with pytest.raises(SystemExit, match="ENV=prod"):
        asyncio.run(main(make_settings(env="prod")))
