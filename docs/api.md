# API Specification (draft)

**Status:** Phase 0 draft. The exact request and response models are defined with Pydantic in the phase that implements each endpoint, and FastAPI's OpenAPI output at `/docs` becomes the source of truth.

## Conventions

- **Auth:** `Authorization: Bearer <JWT>` on every endpoint except `/auth/login`, `/health/*` and the static page.
- **Errors:** every error uses one envelope: `{"error": {"code": "NOT_FOUND", "message": "...", "request_id": "..."}}`.
- **Not found vs. forbidden:** a resource the caller may not see returns `404`, never `403`. `403` is reserved for "you may see it but not do this", for example a buyer calling an approve endpoint.
- **Idempotency:** `POST /conversations/{id}/messages` accepts an `Idempotency-Key` header. A repeated key returns the original run.
- **Money:** `{"amount_minor": 499900, "currency": "INR"}`. Amounts are never floats.

## Endpoints

| Method | Path | Who | Phase | Notes |
|---|---|---|---|---|
| GET | `/health/live` | public | 1 | The process is up |
| GET | `/health/ready` | public | 1 | Postgres and Redis are reachable |
| POST | `/auth/login` | public | 2 | `{tenant_slug, email, password}` → `{access_token, token_type: "bearer", expires_in}` (OD-1). Slug and email are trimmed and lower-cased; unknown fields are rejected (422). Every failure is the same `401 UNAUTHORIZED` "Invalid credentials." Response carries `Cache-Control: no-store` |
| GET | `/auth/me` | any | 2 | The current `AuthContext`: `{user_id, tenant_id, role, scopes}`, read from the token only. A missing, malformed, expired or foreign token is `401 UNAUTHORIZED` "Not authenticated." with `WWW-Authenticate: Bearer` |
| GET | `/orders` | buyer (own), support (tenant) | 3 | Recent orders, paginated |
| GET | `/orders/{id}` | same | 2 | Scope `orders:read`. `{id, order_number, buyer_id, seller_name, status, total: Money, placed_at, delivered_at, items: [{sku, name, quantity, unit_price: Money}]}`. Another buyer's order, another tenant's order and an unknown id all return the same `404 NOT_FOUND` "Order not found." |
| GET | `/orders/{id}/shipment` | same | 3 | Includes recent events |
| GET | `/orders/{id}/refund-eligibility` | same | 3 | `{eligible, reasons[], refundable_remainder}` |
| POST | `/conversations` | any | 4 | |
| GET | `/conversations/{id}/messages` | owner | 4 | |
| POST | `/conversations/{id}/messages` | owner | 4 | → `202 {run_id}` (OD-3) |
| GET | `/runs/{id}` | owner, support | 4 | Status, route, stop reason, usage, cost |
| GET | `/runs/{id}/events` | owner, support | 4 | **SSE**, supports `Last-Event-ID` replay |
| POST | `/runs/{id}/cancel` | owner, support | 9 | Cooperative cancellation |
| GET | `/approvals?status=pending` | support | 7 | The inbox |
| GET | `/approvals/{id}` | support, requester | 7 | Includes the args and hash |
| POST | `/approvals/{id}/approve` | support (≠ requester) | 7 | `{reason?}` |
| POST | `/approvals/{id}/reject` | support (≠ requester) | 7 | `{reason}` |
| GET | `/memories` | owner | 6 | Users can see what the agent remembers |
| DELETE | `/memories/{id}` | owner | 6 | |
| POST | `/admin/policies` | support (`policies:manage`) | 3 | Ingest or re-embed policy documents |
| GET | `/` | public | 4+ | The static demo page (no build step) |

## SSE events

The stream is `GET /runs/{id}/events`. Each event's `id` is its Redis Stream entry id, which is what makes `Last-Event-ID` resumption work.

```
id: 1732190000000-0
event: tool.completed
data: {"run_id":"...","seq":4,"tool":"get_shipment","ok":true,"latency_ms":212}
```

| Event | When |
|---|---|
| `run.started` | The worker claimed the run. This is what time to first event measures. |
| `route.selected` | `fast` or `agent` |
| `llm.started` / `llm.completed` | Around each model call (with usage) |
| `tool.started` / `tool.completed` | Around each tool call (args are redacted where sensitive) |
| `approval.required` | The run is paused (includes `approval_id`) |
| `approval.resolved` | Approved, rejected or expired |
| `message.delta` | Streamed final-answer text |
| `run.completed` | Includes `stop_reason` and usage |
| `run.failed` | Includes an error code |
