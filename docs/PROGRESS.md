# Order Ops Copilot — Progress Log

## Current status

**Phase 2 — Auth and Isolation: IN PROGRESS (Step 2.5, the security suite; the wrap-up below awaits sign-off)**

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

### Phase 1 — Project Foundation and Database ✅ (signed off 2026-11-25)

- **What we built:** a running skeleton. It has:
  - typed settings
  - a FastAPI app factory with structured logging, request ids and one error envelope
  - an async Postgres engine and a Redis client, managed by the lifespan
  - `/health/live` and `/health/ready`
  - Docker Compose: Postgres 17 + pgvector, and Redis
  - two database roles
  - 15 typed models
  - Alembic migrations (a baseline schema, plus append-only audit privileges)
  - a deterministic seed: 2 tenants, 8 users and 16 INR orders, including injection fixtures
- **Concepts covered:**
  - Settings and secrets: fail-fast typed settings, `SecretStr`, and validation errors that never echo input.
  - Logging and requests: structlog through the stdlib with contextvars; pure ASGI middleware vs. `BaseHTTPMiddleware`; one error envelope.
  - Health checks: liveness vs. readiness; lazy pools; the caller owns the deadline (`asyncio.wait_for`).
  - Least privilege: `app_owner` vs. `app_user`, default privileges, and a separate `MigrationSettings` so the runtime never holds the owner credential.
  - Schema rules in the database:
    - a naming convention
    - TIMESTAMPTZ everywhere
    - VARCHAR + CHECK instead of native enums
    - composite tenant-scoped (and currency-scoped) foreign keys
    - invariants as CHECKs (stop reason iff terminal, maker-checker, step shape)
    - `clock_timestamp()` vs. `now()`
    - NULL semantics in UNIQUE constraints and composite FKs
    - JSONB
    - pgvector HNSW
  - Migrations: transactional DDL, `lock_timeout`, offline `--sql` review, and autogenerate's blind spots (CHECK changes, privileges, third-party types).
  - Testing:
    - structural tests over metadata
    - a stairway test with schema+privilege snapshots
    - a models-vs-migrations drift test
    - negative *and* positive privilege tests
    - **mutation testing** to prove that each test can fail
  - Seed data: deterministic uuid5 ids; idempotency via `ON CONFLICT (id)` only; Argon2id with a salt per user; adversarial fixtures.
- **Decisions:**
  - uv and `uv.lock`; Postgres on port 5433 (127.0.0.1).
  - Alembic configured in `pyproject.toml`, with sequential revision ids.
  - Privileges are narrowed in migrations.
  - The seed is deterministic, idempotent and RLS-ready, and refused in prod.
  - No `relationship()` in the models (async lazy-load trap).
  - Refunds require an approval at the schema level (`approval_id NOT NULL`).
- **Tests and results:**
  - **153 tests** (138 unit, 15 integration); ruff clean.
  - Real-Postgres checks: 11 + 18 constraint violations rejected.
  - Mutation runs: 8/8 for migrations and 8/8 for the seed, each re-run on the user's own files.
  - Roadmap exit criteria met:
    - `docker compose up` works.
    - Migrations apply cleanly from empty and downgrade exactly (stairway).
    - Health and database tests pass.
- **Bugs caught in review:**
  - Step 1.4: a zero connect timeout was accepted.
  - Step 1.5b: an FK type mismatch passed 112 unit tests but could not be created in Postgres. This led to the FK type-match test.
  - Step 1.6: two downgrade defects escaped the first stairway test, which led to the snapshot-based stairway.
- **Remaining issues:** none blocking. The optional items are listed under Pending tasks.
- **Next:** Phase 2, Auth and isolation:
  - Argon2 login via tenant slug
  - JWT issue and verify
  - an `AuthContext` dependency
  - a tenant-scoped session helper
  - **RLS policies with FORCE**
  - ownership checks
  - security tests: buyer A can't read buyer B's order; tenant A can't see tenant B even with a missing application filter; no tenant context means zero rows

### Phase 2 — Auth and Isolation (wrap-up drafted 2026-11-28, awaiting sign-off)

- **What we built:**
  - Row-level security on the 14 tenant-owned tables (ENABLE + FORCE, one `tenant_isolation` policy), and `tenant_session()` as the only way to open a tenant-scoped transaction.
  - Argon2id password checks (off the event loop, the same cost for unknown users) and HS256 access tokens with pinned algorithm, issuer, audience and required claims.
  - `POST /auth/login` via tenant slug (OD-1) with one uniform 401, rehash on login, `GET /auth/me`.
  - The Bearer `AuthContext` dependency, per-role scopes and `require_scope` (403).
  - The first service, `services/orders.py`, with one ownership rule, and the first protected read, `GET /orders/{id}` (404 for anything the caller may not see).
  - A named security suite: `uv run pytest -m security`.
- **Concepts covered:**
  - RLS: ENABLE vs. FORCE, USING vs. WITH CHECK, `NULLIF(current_setting(..., true), '')` to fail closed, transaction-local `set_config(..., true)` with pooled connections, and who bypasses RLS anyway (superusers, BYPASSRLS roles, table owners without FORCE).
  - Passwords: Argon2id parameters and rehash, `asyncio.to_thread` for CPU-bound work, timing-safe unknown users (dummy hash), compare-and-swap updates.
  - Tokens: why the server pins the algorithm (`alg: none`, algorithm confusion), `iss`/`aud`, required claims, scopes capped by the role, rejection reasons logged but never sent.
  - 401 vs. 403 vs. 404, and the order they are checked in; ownership as part of the query, so "not yours" and "does not exist" are the same answer.
  - Defence in depth only counts if each layer is tested alone (the application tenant filter vs. RLS).
  - Fail-closed inventories: tables without RLS, routes without a token, roles not yet known (`is not SUPPORT`) all fail or restrict by default.
  - SQLAlchemy async: `expire_on_commit=False`, `DetachedInstanceError` vs. `MissingGreenlet`.
  - Testing: positive controls against vacuous passes, spies, patching where a name is used, simulated races, log-leak canaries, exact response key sets, mutation testing.
- **Decisions:** see the decisions log for 2026-11-25 to 2026-11-28 (RLS policy, tokens, login, ownership in services, exact response fields, the security suite).
- **Tests and results:**
  - **230 tests** (184 unit, 46 integration); **74 in the security suite**; ruff clean.
  - Mutation runs: 2.1 8/8, 2.2 14/14, 2.3 14/14, 2.4 10/11 (1 equivalent by design), 2.5 6/6.
  - Roadmap exit criteria met:
    - Buyer A can't read buyer B's order by id: `test_an_order_the_caller_may_not_see_does_not_exist[another-buyers-order]`, and end to end with an edited token: `test_a_token_edited_to_claim_another_buyer_is_rejected`.
    - Tenant A can't see tenant B even with a missing application filter: `test_a_tenant_sees_only_its_own_rows_even_without_a_filter`, `test_another_tenants_row_is_invisible_even_by_its_id`, and the reverse (only the application filter working) in `test_the_service_filters_by_tenant_even_when_rls_would_not`.
    - No tenant context means zero rows: `test_without_tenant_context_nothing_is_visible` (and writes rejected).
  - Phase 0's open question "RLS when tests run as a superuser" is answered by `test_the_runtime_role_cannot_bypass_rls`: a superuser would skip every policy, so the role the app connects as is checked.
- **Bugs caught in review:**
  - Step 2.1: a seed test passed vacuously over zero rows once RLS hid them; fixed with tenant-scoped queries and a row count.
  - Step 2.2: an unkillable mutant (`return known_user`) exposed a missing test (the dummy hash matching).
  - Step 2.4: `OrderResponse` was missing `delivered_at` and every test still passed; fixed with an exact-keys assertion.
- **Remaining issues:** none blocking. Open items under Pending tasks: `is_active` is checked only at login, no login rate limit yet, the API docs are public in every environment, and dropping only a route's scope (keeping the token check) is not observable until some role lacks `orders:read`.
- **Next:** Phase 3, Domain services and tools: order, shipment and refund services (eligibility, remainder, locking), the email outbox, a mock carrier, policy ingestion with hybrid retrieval, the `ToolSpec` registry with strict schemas, the 7 tools, and the REST read endpoints.

## Phase 1 plan

| Step | Scope | Status |
|---|---|---|
| 1.1 | Project layout, dependency management (uv: `pyproject.toml` + `uv.lock`), `.gitignore`, `.env.example`, typed settings (`pydantic-settings`), first unit tests, ruff | ✅ Done (commit 8359c22) |
| 1.2 | Docker Compose: Postgres + pgvector, Redis, database roles (`app_owner`, `app_user`) init script | ✅ Done (verified 2026-11-22) |
| 1.3 | FastAPI app factory, structured JSON logging (structlog), request-id middleware, error envelope | ✅ Done (commit 836d71f) |
| 1.4 | Async SQLAlchemy engine and session, Redis client, lifespan management, `/health/live`, `/health/ready` | ✅ Done (commit d339780 + fix commit) |
| 1.5a | Base, naming convention, column helpers; identity + commerce models (tenants, users, orders, order_items, shipments, shipment_events, refunds); structural tests | ✅ Done (commit dcae748) |
| 1.5b | Agent and approval models (conversations, messages, agent_runs, agent_steps, approvals, approval_audit, audit_log, memories + pgvector); refunds gain approval and run links | ✅ Done (commit b82f158) |
| 1.6 | Alembic (async env, run as `app_owner`), baseline migration, upgrade/downgrade test; audit tables append-only for `app_user` | ✅ Done (commit 6ad0393) |
| 1.7 | Seed script (2 tenants, buyers, support staff, orders in INR), integration tests against real Postgres | ✅ Done (commit 4acb286) |

## Phase 2 plan

| Step | Scope | Status |
|---|---|---|
| 2.1 | Row-level security: migration 0003 (ENABLE + FORCE + `tenant_isolation` policy on the 14 tenant-owned tables), `db/session.py` (`tenant_session`), RLS integration tests; existing tests made tenant-aware | ✅ Committed (`76e61dc`) |
| 2.2 | `app/auth.py`: Argon2id verify (off the event loop) and rehash, HS256 JWT issue and verify, `AuthContext`; JWT settings | ✅ Committed (`0e890a7`) |
| 2.3 | `POST /auth/login` via tenant slug (OD-1) with a uniform 401 for every failure, rehash on login, `GET /auth/me`, the Bearer `AuthContext` dependency (moved here from 2.4: `/auth/me` needs it), session factory in the lifespan | ✅ Committed (`1eaeb53`) |
| 2.4 | `require_scope` (403), `ForbiddenError`, the first service (`services/orders.py`: one ownership rule, application tenant filter as well as RLS), `seed_test_database` test helper; the first protected read (`GET /orders/{id}`): 404 for anything the caller may not see. `is_active` on sensitive endpoints is deferred to the first sensitive endpoint (refunds, Phase 3) | ✅ Committed (`b3b3077`) |
| 2.5 | Security suite: a `security` marker over the existing security tests (`uv run pytest -m security`), plus three new tests: every route needs a token unless it is on the public list; the runtime role cannot bypass RLS; an edited token cannot read another buyer's order end to end. Phase 2 wrap-up | Applied to the repo on request ("make the code change for this time"), uncommitted: 230 tests, 74 in the security suite; 6/6 mutations caught |

## Implemented features

- **Typed settings** (`app/config.py`): loaded once and validated at startup. Secrets (including database and Redis URLs) are `SecretStr`, input is hidden in validation errors, and settings are frozen.
- **App factory** (`app/main.py`): `create_app(settings)`, run with `uvicorn app.main:create_app --factory`.
- **Structured logging** (`app/logging_config.py`): structlog and stdlib logging share one pipeline. JSON in test/prod, console in dev. Every line includes `request_id` (via contextvars) and the logger name. Tracebacks are plain text with no local variables.
- **Request context middleware** (`app/middleware.py`): pure ASGI. Validates or generates `X-Request-ID`, writes one access log line per request (path only), and returns a safe 500 for unexpected exceptions.
- **Error envelope** (`app/errors.py`): every error is `{"error": {code, message, request_id, details?}}`. Validation errors never echo the submitted input. Framework headers (e.g. `Allow`) are preserved.
- **ORM models, identity and commerce** (`db/base.py`, `db/models.py`): tenants, users, orders, order_items, shipments, shipment_events, refunds. Includes a naming convention, timestamps that are always TIMESTAMPTZ, statuses stored as VARCHAR + CHECK, composite tenant-scoped foreign keys (plus currency for items and refunds), and a unique idempotency key on refunds. Tables are created by Alembic migrations (Step 1.6).
- **Structural schema tests** (`tests/unit/test_models.py`): tenant_id on every table, tenant_id in every reference between tenant tables, money as BIGINT with currency, timezone-aware timestamps, DDL compiles and names are ≤ 63 characters.
- **Migrations** (`db/migrations/`, `[tool.alembic]` in `pyproject.toml`): async `env.py` running as `app_owner` via `MigrationSettings`, `lock_timeout = 5s`, a pgvector render hook, and offline `--sql` mode. `0001_baseline_schema` (autogenerated, reviewed) creates all 15 tables. `0002_runtime_role_privileges` makes `approval_audit` and `audit_log` append-only for `app_user` and hides `alembic_version` from it.
- **Migration tests**: a single head and offline rendering (unit); a stairway with schema+privilege snapshots, models vs. migrations drift, and runtime-role privilege checks, both negative and positive (integration).
- **Seed** (`db/seed.py`, `uv run python -m db.seed`): 2 tenants × (4 users, 8 orders covering delivered, in transit, overdue, placed, cancelled, outside the refund window, lost, and an injection note). Deterministic, idempotent, runs as `app_user`, refuses `ENV=prod`.
- **Local infrastructure** (`docker-compose.yml`): Postgres 17.12 + pgvector 0.8.7 on `127.0.0.1:5433`, and Redis 7.4 on `127.0.0.1:6379` with persistence disabled on purpose (ADR-0002).
- **Database roles** (`infra/postgres/init/01-roles-and-databases.sh`): `app_owner` (owns the schema, used for migrations) and `app_user` (runtime; no DDL, no BYPASSRLS). Default privileges mean future tables are automatically granted SELECT/INSERT/UPDATE/DELETE to `app_user`. Databases: `orderops` and `orderops_test`.

## Decisions log

- **2026-11-21: uv replaces pip-tools for dependency management.** Direct dependencies live in `pyproject.toml` `[project.dependencies]`, and dev tools go in `[dependency-groups].dev`. `uv.lock` is the cross-platform pinned lock and gets committed. Python is pinned with `.python-version` (3.12), and `requires-python = ">=3.12"`. The old `requirements.txt` and `requirements-dev.in` are redundant now.

- **2026-11-22: Alembic is configured in `pyproject.toml` (`[tool.alembic]`), with no `alembic.ini`.** Revision ids are sequential and readable (`--rev-id 0001`). The owner credential is read by a separate `MigrationSettings`, so the runtime `Settings` cannot load it. Migrations connect with `lock_timeout = 5s` and `application_name = order-ops-migrations`. Generated migrations go through `ruff check --fix` and `ruff format` (post-write hooks); E501 is ignored for `db/migrations/versions/*` only.
- **2026-11-22: privileges are changed in migrations, not in the init script.** The init script grants `app_user` default DML on every new table. Migration 0002 narrows that: `approval_audit` and `audit_log` lose UPDATE/DELETE, and `alembic_version` loses everything.

- **2026-11-25: the seed is deterministic and idempotent.** Ids are `uuid5(SEED_NAMESPACE, name)`, and inserts use `ON CONFLICT (id) DO NOTHING`, so conflicts on any *other* unique column still fail loudly. It runs as `app_user`, one transaction per tenant with `app.tenant_id` set, so it already matches Phase 2's RLS. Demo passwords come from `SEED_USER_PASSWORD` (12+ characters) and are hashed with Argon2id (`argon2-cffi`, ADR-0004). The seed refuses to run with `ENV=prod`. Both tenants deliberately share emails and order numbers, and the data includes two prompt-injection fixtures (a buyer note and a carrier event) for Phases 7 and 8.

- **2026-11-25: one RLS policy, `tenant_isolation`, for all roles, on every table with `tenant_id`; `tenants` has none (OD-1).** `ENABLE` + `FORCE`, so the owner is filtered too. The table list is frozen inside migration 0003, not imported from the models. A test derives the expected list from the models, so a future tenant table fails until its migration adds RLS. Sessions come from `db/session.py` `tenant_session()` only: one transaction, `set_config(..., true)`, commit on success, rollback on error, with `expire_on_commit=False`.

- **2026-11-25: access tokens (ADR-0004, refined).** PyJWT, HS256 only, with the algorithm pinned by the server. Claims: `iss`, `aud`, `sub`, `tenant_id`, `role`, `scopes`, `iat`, `exp`, `jti`; all required. `iss` and `aud` were added to the ADR's list so a token minted for another service with the same key is refused. `JWT_SECRET` must be 32+ characters; `ACCESS_TOKEN_TTL_SECONDS` defaults to 900, bounded to 60–3600. Scopes are an explicit allow-list per role (`ROLE_SCOPES`), and verification rejects a token whose scopes exceed what its role allows today. Argon2 hashing and verification run in a worker thread; an unknown user is verified against a dummy hash so timing does not reveal which emails exist; a corrupt stored hash fails closed.

- **2026-11-25: login (OD-1).** `authenticate()` reads `tenants` in a session with no tenant set (that table has no RLS; every other table shows zero rows there), then the user inside `tenant_session`. Every failure path (unknown tenant, unknown email, wrong password, inactive account) runs exactly one Argon2 verification and returns the same 401. The database transaction ends before Argon2 runs, so a slow hash never holds a pooled connection. An outdated hash is replaced on login with a compare-and-swap `UPDATE … WHERE password_hash = <the hash just verified>`, so a password changed meanwhile is never overwritten. Logs name the tenant slug or user id, never the email, password or token. `AppError` subclasses can carry response headers (`AuthenticationError` sends `WWW-Authenticate: Bearer`).

- **2026-11-26: ownership lives in services, as a query filter.** `services/orders.visible_orders(auth)` is the single starting point for every order query: the tenant filter (repeating RLS, so either layer alone isolates tenants) plus, for every role except support, `buyer_id = caller`. Fail-closed for roles added later. The check is part of the query, not a check after fetching, so "not yours" and "does not exist" take the same path and return the same 404. Services return `None` for "not visible"; the API turns it into `NotFoundError` (services know nothing about HTTP). Routes open `tenant_session(sessions, auth.tenant_id)` explicitly rather than through a yield dependency, so the commit visibly happens before the response is built.
- **2026-11-28: response tests pin the exact set of fields.** Pydantic silently drops keyword arguments a model does not declare, so a missing field in a response model is invisible unless a test asserts the key set. The same assertion catches a column exposed by accident (for example `buyer_note`). Every new response model gets one exact-keys assertion.
- **2026-11-28: the security suite is a pytest marker, not a separate folder.** `@pytest.mark.security` (or a module `pytestmark`) tags every test whose failure means a leak or a bypass, wherever it lives; `uv run pytest -m security` runs exactly those, and Phase 8's CI gate can require 100% of them. New in 2.5: `tests/unit/test_route_protection.py` calls every route without a token and expects 401, except an explicit `PUBLIC` list that must name only real routes; it walks routes with `fastapi.routing.iter_route_contexts` because FastAPI 0.165 keeps included routers as wrappers in `app.routes` (a positive control fails loudly if that walk changes). `test_the_runtime_role_cannot_bypass_rls` checks that the app's role, directly or through membership, is not a superuser, has no BYPASSRLS and owns no table, with `app_owner` as the control.
- **2026-11-26: correction on `expire_on_commit=False`.** Without it, reading an attribute after the session block has closed raises `DetachedInstanceError` (seen in Step 2.4's mutation run), and reading one after a commit while the session is still open raises `MissingGreenlet` (an implicit async reload). Both are prevented by the setting.

## Database changes

- 2026-11-22: Cluster initialised by the init script. Created roles `app_owner` and `app_user` (both NOSUPERUSER, NOBYPASSRLS), databases `orderops` and `orderops_test` (owned by `app_owner`, CONNECT revoked from PUBLIC), extension `vector` in both, and default privileges for `app_user`. No application tables yet.
- 2026-11-22: `alembic upgrade head` on the dev database `orderops`: 0001 (15 tables, HNSW index on `memories.embedding`) and 0002 (privileges). As `app_user`: `approval_audit`/`audit_log` SELECT and INSERT only; `alembic_version` no access; `refunds` full DML.
- 2026-11-25: dev database `orderops` seeded (`python -m db.seed`): 2 tenants, 8 users, 16 orders, 18 items, 12 shipments, 20 events. A second run inserted 0 rows.

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
| 2026-11-26 | 2.4 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 225 passed / 181 passed, 44 deselected · clean |
| 2026-11-28 | 2.5 (applied) | Verified files copied into the repo; the user's partial typing had `from pydantic import json` (an IDE auto-import) where `import json` was meant · ruff · suites | Tagged files gained only the 23 `@pytest.mark.security` lines · clean · 184 passed, 46 deselected / 74 security / 230 passed ✅ |
| 2026-11-28 | 2.5 (scratch) | `uv run pytest` / `-m "not integration"` / `-m security` · ruff | 230 passed / 184 passed, 46 deselected / 74 passed, 156 deselected · clean |
| 2026-11-28 | 2.5 (scratch) | Mutations: `/auth/me` without a token · a new route without a token · a hidden (`include_in_schema=False`) route without a token · a stale `PUBLIC` entry · walking `app.routes` directly · signature not verified | 6/6 caught ✅. With the signature unchecked, the edited token read asha's order (200), so the end-to-end test guards a real attack |
| 2026-11-28 | 2.5 (scratch) | `BYPASS_POWERS` query as three roles (read-only) | app_user (False, 0) · app_owner (False, 16) · superuser (True, 16): the query tells them apart ✅ |
| 2026-11-28 | 2.4 (review) | Typed code vs. scratch · ruff · full suite · mutations · dev DB | `OrderResponse` was missing `delivered_at`, and all 225 tests still passed: Pydantic ignores the unknown keyword in `from_details`. Fix: `test_a_buyer_reads_their_own_order` now pins the exact response key set, `status` and a non-null `delivered_at` (fails on the gap, passes on the fix, also fails if `buyer_note` leaks). 11 mutations: 10 caught, 1 equivalent by design. Dev DB: asha 200 (9 fields), ravi 404, Alpha's meera 200, Beta's meera 404; no tokens or passwords in the logs |
| 2026-11-26 | 2.4 (scratch) | Mutations: no buyer filter · role condition inverted · no application tenant filter · items not filtered by order · scope check removed · default `expire_on_commit` · a 404 message naming the id · 403 instead of 404 · the route requires the wrong scope · items query without its tenant filter | 9/10 caught ✅. The last is equivalent by design: the order is already tenant-checked, and that filter exists for the `(tenant_id, order_id)` index. Also not observable yet: dropping `require_scope` from the route, since both roles hold `orders:read` |
| 2026-11-26 | 2.3 review | User's files vs. the verified code | Logic identical. Comments and docstrings left out (as agreed, only the essential ones are now shown). `verify_password(..., password=password)` is called by keyword, and the test's counting wrapper was renamed to match: consistent |
| 2026-11-26 | 2.3 review | User's tree: ruff · `pytest -m "not integration"` · `pytest` · 14 mutations re-run | clean · 178 passed, 35 deselected · 213 passed · 14/14 caught ✅ |
| 2026-11-26 | 2.3 review | Dev DB `orderops`, in-process app, password read from `.env` (never printed) | alpha asha → 200, buyer, 6 scopes · beta meera → 200, support, 7 scopes · wrong password → 401 UNAUTHORIZED ✅ |
| 2026-11-25 | 2.3 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 213 passed / 178 passed, 35 deselected · clean (one S105 false positive on `token_type` suppressed inline) |
| 2026-11-25 | 2.3 (scratch) | Mutations: inactive accounts allowed · unknown tenant skips Argon2 · unknown email skips Argon2 · extra body fields allowed · no lower-casing · no rehash · rehash without the compare-and-swap · no `Cache-Control` · email logged on failure · a distinct message for an unknown tenant · token error reason sent to the client · token logged · `WWW-Authenticate` dropped · no password length cap | 14/14 caught ✅ |
| 2026-11-25 | 2.2 review | User's files vs. scratch | Code identical. `app/auth.py`, `app/config.py` and `.env.example` were typed without most of their comments and docstrings; `test_config.py` has the new tests in a different position (no effect) |
| 2026-11-25 | 2.2 review | User's tree: ruff · `pytest -m "not integration"` · `pytest` · 14 mutations re-run · `.env` checked by key and length only | clean · 168 passed, 24 deselected · 192 passed · 14/14 caught ✅ · `JWT_SECRET` present once, 64 characters |
| 2026-11-25 | 2.2 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 192 passed / 168 passed, 24 deselected · clean |
| 2026-11-25 | 2.2 (scratch) | Mutations: also accept HS512 · audience not verified · `exp` not required · signature not verified · no scope-vs-role check · unknown user returns early · verify on the event loop · hash on the event loop · `return True` for an unknown user · only `VerificationError` caught · buyers may approve · constant `jti` · `JWT_SECRET` without a minimum length · an extra `email` claim | 14/14 caught ✅ |
| 2026-11-25 | 2.1 review | User's files vs. scratch | Migration, support, seed and RLS tests identical. Nits: the migration file is named `003_` (not `0003_`), `db/session.py` has no comments or docstrings, and the snapshot comment in `test_migrations.py` still mentions only GRANTs |
| 2026-11-25 | 2.1 review | User's tree: ruff · `pytest -m "not integration"` · `pytest` · 8 mutations re-run | clean · 138 passed, 24 deselected · 162 passed · 8/8 caught ✅ |
| 2026-11-25 | 2.1 review | Dev DB `orderops` as app_user after `alembic upgrade head` | Without a tenant: orders 0, users 0, tenants 2 (directory, no RLS). With each tenant: 8 orders, one distinct tenant_id ✅ |
| 2026-11-25 | 2.1 (scratch) | Migration 0003 alone, before fixing the tests | 2 seed tests failed (unscoped queries see 0 rows), and `test_passwords_are_stored_as_argon2id_hashes` passed **vacuously** over 0 rows. Fixed with tenant-scoped queries plus a row-count assertion |
| 2026-11-25 | 2.1 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 162 passed / 138 passed, 24 deselected · clean |
| 2026-11-25 | 2.1 (scratch) | Mutations: no NULLIF · no FORCE · WITH CHECK (true) · a table left out · session-level `set_config(..., false)` · no transaction in `tenant_session` · downgrade forgets NO FORCE · downgrade forgets DROP POLICY | 8/8 caught ✅ |
| 2026-11-25 | 1.7 review | User's files vs. scratch | `db/seed.py` and both test files identical; `.env.example` lacks the two comment lines above `SEED_USER_PASSWORD` |
| 2026-11-25 | 1.7 review | `uv run pytest` / `-m "not integration"` · ruff | 153 passed / 138 passed, 15 deselected · clean |
| 2026-11-25 | 1.7 review | The 8 seed mutations on a copy of the user's tree | 8/8 caught; restored tree 12 passed ✅ |
| 2026-11-25 | 1.7 review | Dev database as `app_user` | Counts 2/8/16/18/12/20; 8 distinct argon2id hashes; asha@example.com in 2 tenants; ORD-1003 overdue; every order total = sum of its items ✅ |
| 2026-11-25 | 1.7 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 153 passed / 138 passed, 15 deselected · clean |
| 2026-11-25 | 1.7 (scratch) | Mutations: bare ON CONFLICT DO NOTHING · one hash for all users · prod guard removed · random ids · an order owned by support · delivered without delivered_at · last_event_at from the first event · per-tenant email domains | 8/8 caught ✅ |
| 2026-11-25 | 1.7 (scratch) | `main()` against orderops_test; `ENV=prod python -m db.seed`; missing or short `SEED_USER_PASSWORD` | Re-run inserts 0 rows · exits 1 with `Refusing to seed: ENV=prod` before connecting · ValidationError without echoing the value |
| 2026-11-22 | 1.6 review | User's files vs. scratch | env.py, tests, support and 0001 (apart from date and banner) identical. Nits: MigrationSettings docstring removed, validator renamed `_required_asyncpg_driver`, 0002 Create Date holds placeholder text, no newline at the end of script.py.mako |
| 2026-11-22 | 1.6 review | `uv run pytest` / `-m "not integration"` · ruff | 141 passed / 131 passed, 10 deselected · clean |
| 2026-11-22 | 1.6 review | The 8 mutations on a copy of the user's tree | 8/8 caught; restored tree 8 passed ✅ |
| 2026-11-22 | 1.6 review | Dev database as `app_user` | `alembic current` = 0002 (head); 16 tables (15 + alembic_version); audit tables S/I only; alembic_version none ✅ |
| 2026-11-22 | 1.6 (scratch) | `uv run pytest` / `-m "not integration"` · ruff | 141 passed / 131 passed, 10 deselected · clean |
| 2026-11-22 | 1.6 (scratch) | Migrated schema vs. 1.5b `create_all` | Constraint and index names identical (only `alembic_version_pkc` added) |
| 2026-11-22 | 1.6 (scratch) | Mutations: column added to a model only · embedding dimension changed in the model · server default changed in the model · `drop_table` missing from a downgrade · audit REVOKE removed · REVOKE ALL instead of UPDATE, DELETE · audit GRANT missing from a downgrade · alembic_version GRANT missing from a downgrade | 8/8 caught. The last two were missed at first: the stairway test now compares schema+privilege snapshots and starts from a fresh version table ✅ |
| 2026-11-22 | 1.6 (scratch) | Migration connection | current_user=app_owner, lock_timeout=5s, application_name=order-ops-migrations |
| 2026-11-22 | 1.5b review | Typed models: `create_all` on orderops_test | **Failed** before the fix: `fk_messages_tenant_id_run_id_agent_runs cannot be implemented` (`messages.run_id` typed TEXT, NOT NULL; `content` missing). All 112 unit tests still passed |
| 2026-11-22 | 1.5b review | New test `test_foreign_key_column_types_match` | Fails on the buggy models (`messages.run_id is TEXT, references UUID`), passes 15/15 on the correct ones ✅ |
| 2026-11-22 | 1.5b review (after fix) | `uv run pytest` · ruff · real Postgres | 129 passed · clean · `create_all` OK, happy path OK, 18/18 rejected, 0 tables remain |
| 2026-11-22 | 1.5b (scratch) | Unit suite | 112 passed, 2 deselected; ruff clean (one S105 false positive suppressed inline) |
| 2026-11-22 | 1.5b (scratch) | Real Postgres (orderops_test as app_owner, rolled back) | 15 tables plus an HNSW index. Happy path conversation → run → steps → approval (approved → consumed) → refund → completed succeeds. output_items JSONB round-trips identically. clock_timestamp gives distinct times within one transaction. Cosine search returns the nearest memory. 18/18 violations rejected (no approval, double refund, duplicate approval, self-approval, decision fields, consumed_at, expiry, cross-tenant run, missing or extra stop_reason, partial lease, cross-tenant principal, step shape ×2, duplicate call_id, duplicate seq, memory length, vector dimension). 0 tables remain |
| 2026-11-22 | 1.5a review | Unit / full suite (user's files) | 57 passed, 2 deselected / 59 passed; ruff clean |
| 2026-11-22 | 1.5a review | 11 constraint checks on the user's models (orderops_test, rolled back) | 11/11 rejected by the named constraint; enum stored as its value (`'delivered'`); 0 tables remain |
| 2026-11-22 | 1.5a review | Mutation: single-column `shipments.order_id` FK | Caught: `fk_shipments_order_id_orders on shipments omits tenant_id` ✅ |
| 2026-11-22 | 1.3 | `uv run pytest` | 16 passed (11 new in test_app.py), 1 warning (`httpx2` deprecation) |
| 2026-11-22 | 1.3 review | Mutation check: remove `add_logger_name` | The new `logger` assertion fails with `KeyError: 'logger'`, so the test now guards against that regression ✅ |
| 2026-11-22 | 1.1 (after fixes) | `uv run pytest` · `ruff check` · `ruff format --check` | 5 passed · clean (line length 100, rules E/F/I/B/UP/S/ASYNC) · clean |

## Known bugs / issues

None open. Step 1.5b review findings fixed on 2026-11-22 (by request, "fix it for this time"): `Message.content` restored, `Message.run_id` is `UUID | None` (it was TEXT and NOT NULL, so the FK could not be created), `Converstaion` renamed to `Conversation`, the S105 `noqa` restored, and the stale Refund docstring updated. The FK type-match test closes the gap that let this pass 112 unit tests. Step 1.4 review findings fixed on 2026-11-22: `db_connect_timeout_seconds` is `gt=0` again, with the regression test `test_zero_timeouts_are_rejected` (mutation-checked), and the event name is now `shutdown_completed`.

**Environment notes:**
- A separate local Postgres is listening on `127.0.0.1:5432` and `[::1]:5432`. The project's Postgres is therefore exposed on **5433**, and every URL uses `127.0.0.1` rather than `localhost`.

**Lesson recorded:** when a config file is partly replaced, other sections can vanish without warning. ruff with no config still reported "All checks passed" while checking almost nothing. Run `uv run pytest && uv run ruff check . && uv run ruff format --check .` and `git show --stat HEAD` around every commit.

## Pending tasks

- [x] Docker Desktop 4.99 running (engine 29.9.3, Compose v5.7.0, arm64). Rosetta 2 installed for amd64 images. CLI is in `~/.docker/bin`, which is on PATH via `~/.zprofile` (2026-11-22).
- [x] Commit `docs/` (commit 8359c22).

- [ ] Decide on the test-client dependency. Starlette 1.10 warns that `httpx` with TestClient is deprecated and suggests `httpx2`. Verify `httpx2` on PyPI (maintainer, project links) before adopting it, because a one-character name change is a typosquatting pattern. Until then, stay on `httpx` (warning only).

- [ ] Optional (from the 1.6 review, still open): restore the `MigrationSettings` docstring, rename `_required_asyncpg_driver` to `_require_asyncpg_driver`, replace the 0002 `Create Date` placeholder with `2026-11-22`, and restore the two `.env.example` comments for `SEED_USER_PASSWORD`.
- [ ] Optional: use `SHA256_HEX` in the Refund idempotency CHECK (the regex is currently duplicated), and restore the 1.5b "why" comments, especially the `clock_timestamp()` one on `Message.created_at`.
- [ ] Optional (from the 2.4 review): the comments in `services/orders.py` (above all the fail-closed role rule and the index-only items tenant filter), the docstrings and comments in `app/orders_api.py`, and the `require_scope` docstring.
- [ ] Optional (from the 2.1 review, committed without them): restore the module docstring, the `set_config` comment, the `expire_on_commit` comment and the `tenant_session` docstring in `db/session.py`; update the `SNAPSHOT_QUERIES` comment in `tests/integration/test_migrations.py` to mention row-level security.
- [ ] `is_active` is checked only at login; a deactivated user's token works until it expires (≤ 15 min, ADR-0004). Add the check to the first sensitive endpoint (refund request, Phase 3).
- [ ] `Money` lives in `app/orders_api.py`; move it to a shared schemas module when a second endpoint needs it (Phase 3).
- [ ] Optional: `tests/integration/test_rls.py` and `test_auth_api.py` could use `seed_test_database()` instead of their own seeding fixtures.
- [ ] `/docs`, `/redoc` and `/openapi.json` are public in every environment (listed in `PUBLIC` on purpose). Decide whether to switch them off outside dev (production hardening, Phase 9).
- [ ] Dropping only a route's scope (keeping the token check) is not observable yet: every role holds `orders:read`. The first endpoint some role may not call (refund approval, Phase 3 or 7) makes it testable.
- [ ] Login has no rate limit yet: Argon2's cost is the only brake on password guessing. Add per-account and per-IP limits with the shared Redis token buckets (worker phase).
- [ ] Optional (from the 2.2 review): the security comments in `app/auth.py` (pinned algorithm, dummy hash, worker thread, scope cap, fail-closed `except`), the `jwt_secret` comment in `app/config.py`, and the `openssl rand -hex 32` hint above `JWT_SECRET` in `.env.example`.
- [ ] Optional: restore the four "why" comments in errors.py and middleware.py (validation input omission, no Exception handler, untrusted request id, not BaseHTTPMiddleware). Recommended in the review but not restored.

## Next implementation step

Step 2.5 is in the working tree (applied on request, uncommitted). The user commits it, then signs off Phase 2 (Phase 3 does not start without it).
