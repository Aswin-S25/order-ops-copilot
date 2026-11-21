# ADR-0011: A router runs before the agent

- **Status:** Accepted, 2026-11-21

## Context
Most support requests ("where is my order?") don't need an autonomous loop. Sending them through one costs latency, tokens and reliability.

## Decision
A router classifies each message (rules first, then a cheap structured-output classifier). Order status, shipment status and policy Q&A go to deterministic fast paths. Open-ended, multi-step or side-effecting requests go to the agent loop. Fast-path vs. agent LLM calls and latency are measured (Phase 5). Response contract: see open decision OD-3.

## Consequences
- Lower P95 latency and cost for common requests.
- A misrouted request is its own failure class in evals.
