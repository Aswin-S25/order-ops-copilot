# ADR-0008: Idempotent side effects through unique keys and an outbox

- **Status:** Accepted, 2026-11-21

## Context
Retries, at-least-once job delivery, worker crashes and resumes all re-execute code. The target is zero duplicate side effects.

## Decision
- Every side-effecting tool derives `idempotency_key = sha256(run_id ‖ call_id)` and writes under a `UNIQUE(tenant_id, idempotency_key)` constraint.
- On conflict, it returns the existing result.
- The side-effect row and the step result commit in one transaction.
- Email goes through a transactional outbox (`email_outbox`). A dispatcher delivers with retries, and dedupe uses the same key.
- Before executing a write, the executor checks the step ledger.
- Writes are never retried blindly. Only reads and model calls are retried automatically.

## Consequences
- Exactly-once *effects* on top of at-least-once *delivery*.
- Mock external services must also honour idempotency keys, like real payment providers do.
