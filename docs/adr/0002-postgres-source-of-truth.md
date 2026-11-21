# ADR-0002: PostgreSQL is the source of truth; Redis is disposable

- **Status:** Accepted, 2026-11-21

## Context
Runs can last hours (while waiting for approval) and must survive restarts. Two stores holding authoritative state invites split-brain bugs.

## Decision
All durable state lives in PostgreSQL: business data, runs, steps, checkpoints, approvals, memories, outbox and audit. Redis carries only job delivery, per-run event streams and rate-limit counters. All of it can be rebuilt from Postgres by a reconciler.

## Consequences
- Losing Redis degrades latency and live streaming, but never correctness.
- Every enqueue happens after a commit, and the reconciler covers crashes between the commit and the XADD.

## Alternatives considered
Keeping run state in Redis (fast, but volatile and hard to audit).
