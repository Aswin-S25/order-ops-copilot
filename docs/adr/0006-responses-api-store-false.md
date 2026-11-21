# ADR-0006: Responses API with store=false and verbatim item replay

- **Status:** Accepted, 2026-11-21

## Context
The Responses API is OpenAI's current interface for tool-using agents. It can hold conversation state on OpenAI's side (`previous_response_id`), but then the source of truth would live outside our database and weaken recovery, audit and evals.

## Decision
- We call the Responses API with `store=false` and send the full input on every request.
- Each response's `output` items are persisted verbatim and replayed in their original order, followed by one `function_call_output` per `call_id`.
- For reasoning models we request `include=["reasoning.encrypted_content"]` and replay reasoning items unchanged next to their function calls.
- The model and agent config are pinned per run (`config_version`, `model`).
- Within a run, items are never summarised. Summarisation only applies to conversation history between runs.

## Consequences
- Resume works from any checkpoint, and evals can replay exact inputs.
- Input tokens grow with run length, which budgets and iteration caps bound.
- Encrypted reasoning content is stored but never logged.

## Alternatives considered
Chat Completions (familiar, but no first-class reasoning items). `store=true` with `previous_response_id` (less code, but state is hidden outside our database).
