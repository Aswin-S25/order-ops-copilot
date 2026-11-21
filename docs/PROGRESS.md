# Order Ops Copilot — Progress Log

## Current status

**Phase 1 — Project Foundation and Database: IN PROGRESS (Step 1.1)**

Working agreement: application code is shown in chat and typed in by hand. Only documentation is written directly to the repo.

## Completed phases

### Phase 0 — Requirements and Architecture ✅ (signed off 2026-11-21)

- **What we built:** the architecture ([architecture.md](architecture.md)), data model ([data-model.md](data-model.md)), API specification ([api.md](api.md)), roadmap ([roadmap.md](roadmap.md)) and 13 ADRs ([adr/](adr/)). The base document is [archive/phase0-plan-recovered.md](archive/phase0-plan-recovered.md).
- **Concepts covered:**
  - The model proposes and the server decides (the LLM is not a principal).
  - Confused-deputy risk.
  - Tenant isolation with RLS via `set_config(..., true)`.
  - Responses API replay with `store=false`, including reasoning items.
  - Hash-bound maker-checker approvals.
  - Idempotency keys and the outbox pattern.
  - Pause/resume through checkpoints.
  - Redis delivery vs. Postgres ownership (leases).
  - Time-of-check vs. time-of-use (TOCTOU) re-validation.
- **Decisions:** ADR-0001 to ADR-0013, plus OD-1 to OD-10, all accepted.
- **Tests:** none (design phase).
- **Remaining issues:**
  - The understanding-check questions (RLS when tests run as a superuser; model pinning on resume; a duplicate worker delivery) are still unanswered. They'll be revisited in Phases 2 and 4.

## Phase 1 plan

| Step | Scope | Status |
|---|---|---|
| 1.1 | Project layout, dependency management (uv: `pyproject.toml` + `uv.lock`), `.gitignore`, `.env.example`, typed settings (`pydantic-settings`), first unit tests, ruff | In progress |
| 1.2 | Docker Compose: Postgres + pgvector, Redis, database roles (`app_owner`, `app_user`) init script | Pending |
| 1.3 | FastAPI app factory, structured JSON logging (structlog), request-id middleware, error envelope | Pending |
| 1.4 | Async SQLAlchemy engine and session, Redis client, lifespan management, `/health/live`, `/health/ready` | Pending |
| 1.5 | SQLAlchemy models for the core tables | Pending |
| 1.6 | Alembic (async env, run as `app_owner`), baseline migration, upgrade/downgrade test | Pending |
| 1.7 | Seed script (2 tenants, buyers, support staff, orders in INR), integration tests against real Postgres | Pending |

## Implemented features

None yet.

## Decisions log

- **2026-11-21: uv replaces pip-tools for dependency management.** Direct dependencies live in `pyproject.toml` `[project.dependencies]`, and dev tools go in `[dependency-groups].dev`. `uv.lock` is the cross-platform pinned lock and gets committed. Python is pinned with `.python-version` (3.12), and `requires-python = ">=3.12"`. The old `requirements.txt` and `requirements-dev.in` are redundant now.

## Database changes

None yet.

## Tests and results

| Date | Step | Command | Result |
|---|---|---|---|
| 2026-11-22 | 1.1 | `pytest` | 5 passed (test_config.py) |
| 2026-11-22 | 1.1 | `ruff check .` / `ruff format --check .` | Clean |
| 2026-11-22 | 1.1 | Load real `.env` through `get_settings()` (values not printed) | Loads OK |

## Known bugs / issues

Second Step 1.1 review (2026-11-22):
- **[blocking, regression]** The `[tool.pytest.ini_options]` and `[tool.ruff]` sections are missing from `pyproject.toml` (they were dropped in commit 69a1b05). `pytest` now fails at collection with `ModuleNotFoundError: No module named 'app'`. ruff falls back to its defaults (only the E/F rules, line length 88), so "All checks passed" is misleading.
- **[blocking]** `.gitignore` still contains `docs/`. 0 files under docs/ are tracked, even though commit 69a1b05 says "Add Phase 0 design docs".
- **[open]** Step 1.2 files (`docker-compose.yml`, `infra/postgres/init/…`, the new `.env` keys) don't exist yet. Docker is still not installed.
- **[nit]** The `app/config.py:30` error message says "schema" where it should say "scheme".
- Fixed: uv migration (`[project]`, `[dependency-groups]`, `uv.lock`, requirements files removed) ✅

## Pending tasks

- [ ] Install or start Docker (Docker Desktop, OrbStack or Colima). The `docker` command is not on PATH. This is needed for Step 1.2.
- [ ] Commit `docs/` once `.gitignore` is fixed. The repo has 2 commits, but neither includes the docs.

## Next implementation step

Close out Step 1.1 by fixing the review findings. Then Step 1.2: Docker Compose (Postgres + pgvector, Redis) and the database-roles init script. Docker must be installed first.
