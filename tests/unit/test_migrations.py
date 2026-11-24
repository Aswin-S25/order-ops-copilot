"""Migration checks that need no database."""

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from tests.support import alembic_config


def test_migration_history_has_a_single_head() -> None:
    # Two branches that each add a migration produce two heads; `upgrade head` then fails.
    # Catch it in CI, before it reaches a deploy.
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_offline_sql_renders_without_a_database(capsys: pytest.CaptureFixture[str]) -> None:
    # `alembic upgrade head --sql` is how the SQL gets reviewed before it runs.
    command.upgrade(alembic_config(), "head", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE tenants" in sql
    assert "USING hnsw (embedding vector_cosine_ops)" in sql
    assert "REVOKE UPDATE, DELETE ON approval_audit, audit_log FROM app_user" in sql
