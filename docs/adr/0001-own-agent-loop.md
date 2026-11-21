# ADR-0001: Build our own agent loop on the OpenAI SDK

- **Status:** Accepted, 2026-11-21

## Context
Agent frameworks (LangChain, LangGraph) hide the tool-calling lifecycle: item replay, call-id pairing, stop conditions and retries. This project exists to understand and control exactly that lifecycle, and to make every step persistable and auditable.

## Decision
We implement the loop controller, context builder, tool registry, executor and policy gate ourselves on the official OpenAI Python SDK. Only `agent/llm_gateway.py` imports `openai`.

## Consequences
- We fully control persistence, idempotency, approvals and stop reasons.
- We write more code and own more bugs, which the eval suite has to catch.
- A framework can be evaluated later against a working baseline.

## Alternatives considered
LangGraph (has checkpointing built in, but hides the mechanics we want to learn). Agents SDKs (same trade-off).
