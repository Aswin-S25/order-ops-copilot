# Architecture Decision Records

Each ADR records one decision: its context, the decision, its consequences and the alternatives considered. ADRs are never edited after acceptance. A changed decision gets a new ADR that supersedes the old one.

The smaller follow-up decisions OD-1 to OD-10 (login tenant resolution, cross-tenant system jobs, response contract, SSE auth, approval reservation, async DB, RAG corpus, eval cadence, embeddings, primary keys) were accepted on 2026-11-21. They are recorded in [architecture.md §12](../architecture.md#12-phase-0-follow-up-decisions-all-accepted-2026-11-21).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-own-agent-loop.md) | Build our own agent loop on the OpenAI SDK | Accepted |
| [0002](0002-postgres-source-of-truth.md) | PostgreSQL is the source of truth; Redis is disposable | Accepted |
| [0003](0003-tenancy-and-rls.md) | Tenant = marketplace operator; isolation via app filters plus RLS | Accepted |
| [0004](0004-self-issued-jwt.md) | Self-issued JWTs with Argon2, short-lived, no refresh tokens | Accepted |
| [0005](0005-identity-never-from-llm.md) | Identity reaches tools only through the server context | Accepted |
| [0006](0006-responses-api-store-false.md) | Responses API with store=false and verbatim item replay | Accepted |
| [0007](0007-hash-bound-approvals.md) | Hash-bound, single-use, maker-checker approvals | Accepted |
| [0008](0008-idempotent-side-effects.md) | Idempotent side effects through unique keys and an outbox | Accepted |
| [0009](0009-pause-releases-worker.md) | Pausing releases the worker; resuming replays from a checkpoint | Accepted |
| [0010](0010-redis-streams-worker-phase4.md) | Minimal Redis Streams worker from Phase 4; Postgres lease owns the run | Accepted |
| [0011](0011-router-before-agent.md) | A router runs before the agent | Accepted |
| [0012](0012-money-and-partial-refunds.md) | Money in minor units with currency; partial refunds | Accepted |
| [0013](0013-api-first-static-ui.md) | API-first with a static HTML demo page | Accepted |
