# ADR-0010: Minimal Redis Streams worker from Phase 4; Postgres lease owns the run

- **Status:** Accepted, 2026-11-21

## Context
The brief puts queues in Phase 9, but Phases 4 to 8 already need durable runs, pause and resume, and SSE from a separate process. Building an in-process executor first and rewriting it later would waste effort.

## Decision
- In Phase 4 we introduce a worker on raw Redis Streams: consumer group `workers`, `XREADGROUP` for new jobs, `XAUTOCLAIM` for jobs left by crashed consumers, and `XACK` only after the run state commits. We don't use Celery, RQ or arq.
- **Redis decides delivery; Postgres decides ownership:** a conditional `UPDATE` claims a lease (`lease_owner`, `lease_expires_at`), and heartbeats extend it.
- A reconciler re-enqueues orphaned runs from Postgres.
- Phase 9 hardens this worker (concurrency limits, graceful shutdown, shared rate limits, budgets, cancellation, load tests) rather than replacing it.

## Consequences
- We learn the queue semantics directly: at-least-once delivery, pending entry lists, idle reclaiming.
- Duplicate deliveries are expected and handled by the lease and idempotency.
