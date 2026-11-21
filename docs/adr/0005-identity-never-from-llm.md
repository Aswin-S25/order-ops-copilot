# ADR-0005: Identity reaches tools only through the server context

- **Status:** Accepted, 2026-11-21

## Context
An agent acting with a user's authority is a confused deputy. If identity ever came from model-generated arguments, a prompt injection could impersonate another user.

## Decision
- No tool argument schema contains `user_id`, `tenant_id`, `role` or any similar field.
- Tools receive a `ToolContext` built from the run's recorded principal (originally taken from the verified JWT).
- Tools are thin adapters over the same domain services the REST API uses, so ownership is checked in exactly one place.
- Inaccessible resources return `NOT_FOUND`.
- Tool schemas are filtered by the principal's scopes before being sent to the model.

## Consequences
- A fully hijacked model can do nothing beyond what the human principal can do.
- The `services/` package is added to the brief's repository layout.
