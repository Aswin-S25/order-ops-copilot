# ADR-0009: Pausing releases the worker; resuming replays from a checkpoint

- **Status:** Accepted, 2026-11-21

## Context
Human approval can take hours. Blocking a worker slot or an HTTP connection that long doesn't scale and doesn't survive restarts.

## Decision
- When a call needs approval, the run is checkpointed and set to `awaiting_approval`, its lease is released, and its job is acknowledged.
- An approval decision (or expiry) enqueues `resume_run`.
- The resuming worker restores the checkpoint, answers the pending `call_id`, and continues the loop.

## Consequences
- `awaiting_approval` is a suspended state, not a stop reason.
- The client learns the outcome through SSE if it's still connected, otherwise through run status and conversation history.
