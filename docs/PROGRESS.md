# Order Ops Copilot — Progress Log

## Current status

**Phase 1 — Project Foundation and Database: IN PROGRESS (Step 1.5a)**

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
| 1.1 | Project layout, dependency management (uv: `pyproject.toml` + `uv.lock`), `.gitignore`, `.env.example`, typed settings (`pydantic-settings`), first unit tests, ruff | ✅ Done (commit 8359c22) |
| 1.2 | Docker Compose: Postgres + pgvector, Redis, database roles (`app_owner`, `app_user`) init script | ✅ Done (verified 2026-11-22) |
| 1.3 | FastAPI app factory, structured JSON logging (structlog), request-id middleware, error envelope | ✅ Done (commit 836d71f) |
| 1.4 | Async SQLAlchemy engine and session, Redis client, lifespan management, `/health/live`, `/health/ready` | ✅ Done (commit d339780 + fix commit) |
| 1.5a | Base, naming convention, column helpers; identity + commerce models (tenants, users, orders, order_items, shipments, shipment_events, refunds); structural tests | In progress: verified in a scratch copy (59 tests + 11 constraint checks against real Postgres) |
| 1.5b | Agent and approval models (conversations, messages, agent_runs, agent_steps, approvals, approval_audit, audit_log, memories + pgvector); refunds gain approval and run links | Pending |
| 1.6 | Alembic (async env, run as `app_owner`), baseline migration, upgrade/downgrade test | Pending |
| 1.7 | Seed script (2 tenants, buyers, support staff, orders in INR), integration tests against real Postgres | Pending |

## Implemented features

- **Typed settings** (`app/config.py`): loaded once and validated at startup. Secrets (including database and Redis URLs) are `SecretStr`, input is hidden in validation errors, and settings are frozen.
- **App factory** (`app/main.py`): `create_app(settings)`, run with `uvicorn app.main:create_app --factory`.
- **Structured logging** (`app/logging_config.py`): structlog and stdlib logging share one pipeline. JSON in test/prod, console in dev. Every line includes `request_id` (via contextvars) and the logger name. Tracebacks are plain text with no local variables.
- **Request context middleware** (`app/middleware.py`): pure ASGI. Validates or generates `X-Request-ID`, writes one access log line per request (path only), and returns a safe 500 for unexpected exceptions.
- **Error envelope** (`app/errors.py`): every error is `{"error": {code, message, request_id, details?}}`. Validation errors never echo the submitted input. Framework headers (e.g. `Allow`) are preserved.
- **Local infrastructure** (`docker-compose.yml`): Postgres 17.12 + pgvector 0.8.7 on `127.0.0.1:5433`, and Redis 7.4 on `127.0.0.1:6379` with persistence disabled on purpose (ADR-0002).
- **Database roles** (`infra/postgres/init/01-roles-and-databases.sh`): `app_owner` (owns the schema, used for migrations) and `app_user` (runtime; no DDL, no BYPASSRLS). Default privileges mean future tables are automatically granted SELECT/INSERT/UPDATE/DELETE to `app_user`. Databases: `orderops` and `orderops_test`.

## Decisions log

- **2026-11-21: uv replaces pip-tools for dependency management.** Direct dependencies live in `pyproject.toml` `[project.dependencies]`, and dev tools go in `[dependency-groups].dev`. `uv.lock` is the cross-platform pinned lock and gets committed. Python is pinned with `.python-version` (3.12), and `requires-python = ">=3.12"`. The old `requirements.txt` and `requirements-dev.in` are redundant now.

## Database changes

- 2026-11-22: Cluster initialised by the init script. Created roles `app_owner` and `app_user` (both NOSUPERUSER, NOBYPASSRLS), databases `orderops` and `orderops_test` (owned by `app_owner`, CONNECT revoked from PUBLIC), extension `vector` in both, and default privileges for `app_user`. No application tables yet.

## Tests and results

| Date | Step | Command | Result |
|---|---|---|---|
| 2026-11-22 | 1.1 | `pytest` | 5 passed (test_config.py) |
| 2026-11-22 | 1.1 | `ruff check .` / `ruff format --check .` | Clean |
| 2026-11-22 | 1.1 | Load real `.env` through `get_settings()` (values not printed) | Loads OK |
| 2026-11-22 | 1.2 | `docker compose up -d` → `ps` | postgres and redis both `healthy` |
| 2026-11-22 | 1.2 | Role flags | `app_owner` and `app_user`: rolsuper, rolbypassrls, rolcreatedb and rolcreaterole all false |
| 2026-11-22 | 1.2 | Database ACLs | Only `app_owner` and `app_user` may CONNECT; PUBLIC may not |
| 2026-11-22 | 1.2 | NEGATIVE: `app_user` CREATE TABLE | `permission denied for schema public` ✅ |
| 2026-11-22 | 1.2 | Default privileges probe (`orderops_test`, rolled back) | `app_user` INSERT and SELECT ok; TRUNCATE denied; DROP denied (`must be owner`) ✅ |
| 2026-11-22 | 1.2 | Host connection via `get_settings().database_url` | user=app_user, db=orderops, server 17.12, vector 0.8.7 (the container, not the local Postgres on 5432) ✅ |
| 2026-11-22 | 1.2 | Redis via `REDIS_URL` | PING ok; save disabled; appendonly no ✅ |
| 2026-11-22 | 1.4 | `uv run pytest` (Docker up) / `-m "not integration"` | 22 passed / 20 passed, 2 deselected |
| 2026-11-22 | 1.4 review | `db_connect_timeout_seconds=0` against real Postgres | Settings accepted it; connection FAILED with `TimeoutError` (bug confirmed) |
| 2026-11-22 | 1.4 fix | Steps 1.1–1.4 suite (Docker up) | 25 passed; `db_connect_timeout_seconds=0` now rejected at startup |
| 2026-11-22 | 1.5a (scratch) | Unit suite including structural model tests | 59 passed |
| 2026-11-22 | 1.5a (scratch) | `create_all` on orderops_test as app_owner, 11 bad inserts, then rollback | All 11 rejected by the named constraint (cross-tenant FK ×2, currency mismatch, amount 0, key format, duplicate idempotency key, enum, uppercase email, lowercase currency, quantity 0, tenant delete). 0 tables remain afterwards |
| 2026-11-22 | 1.3 | `uv run pytest` | 16 passed (11 new in test_app.py), 1 warning (`httpx2` deprecation) |
| 2026-11-22 | 1.3 review | Mutation check: remove `add_logger_name` | The new `logger` assertion fails with `KeyError: 'logger'`, so the test now guards against that regression ✅ |
| 2026-11-22 | 1.1 (after fixes) | `uv run pytest` · `ruff check` · `ruff format --check` | 5 passed · clean (line length 100, rules E/F/I/B/UP/S/ASYNC) · clean |

## Known bugs / issues

None open. Step 1.4 review findings fixed on 2026-11-22: `db_connect_timeout_seconds` is `gt=0` again, with the regression test `test_zero_timeouts_are_rejected` (mutation-checked), and the event name is now `shutdown_completed`.

**Environment notes:**
- A separate local Postgres is listening on `127.0.0.1:5432` and `[::1]:5432`. The project's Postgres is therefore exposed on **5433**, and every URL uses `127.0.0.1` rather than `localhost`.

**Lesson recorded:** when a config file is partly replaced, other sections can vanish without warning. ruff with no config still reported "All checks passed" while checking almost nothing. Run `uv run pytest && uv run ruff check . && uv run ruff format --check .` and `git show --stat HEAD` around every commit.

## Pending tasks

- [x] Docker Desktop 4.99 running (engine 29.9.3, Compose v5.7.0, arm64). Rosetta 2 installed for amd64 images. CLI is in `~/.docker/bin`, which is on PATH via `~/.zprofile` (2026-11-22).
- [x] Commit `docs/` (commit 8359c22).

- [ ] Decide on the test-client dependency. Starlette 1.10 warns that `httpx` with TestClient is deprecated and suggests `httpx2`. Verify `httpx2` on PyPI (maintainer, project links) before adopting it, because a one-character name change is a typosquatting pattern. Until then, stay on `httpx` (warning only).

- [ ] Optional: restore the four "why" comments in errors.py and middleware.py (validation input omission, no Exception handler, untrusted request id, not BaseHTTPMiddleware). Recommended in the review but not restored.

## Next implementation step

Step 1.5a: the user is typing `db/base.py`, `db/models.py` and `tests/unit/test_models.py`. Then a review, including the 11 constraint checks against real Postgres.
