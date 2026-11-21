# Data Model

**Status:** Phase 0 draft. The tables are built in Phase 1, RLS policies are added in Phase 2, and tables are refined in later phases as noted.
**Conventions:** UUID primary keys, `timestamptz` everywhere, money as `amount_minor BIGINT` + `currency CHAR(3)`. Every tenant-owned table has `tenant_id UUID NOT NULL REFERENCES tenants(id)` and the RLS policy described in [architecture.md §8](architecture.md#8-tenant-isolation-application-filtering-plus-rls).

## ER overview

```
tenants 1──* users (role: buyer|support)
tenants 1──* orders *──1 users (buyer)
               orders 1──* order_items
               orders 1──* shipments 1──* shipment_events
               orders 1──* refunds ──1 approvals            (refunds.approval_id UNIQUE)
                                   └──► agent_runs           (created_by_run_id)

users 1──* conversations 1──* messages
           conversations 1──* agent_runs 1──* agent_steps
                              agent_runs 1──* approvals ──1 agent_steps (the paused call)
                                              approvals 1──* approval_audit
users 1──* memories                    (embedding, source_run_id → agent_runs)
tenants 1──* policy_documents 1──* policy_chunks (embedding + tsvector)
tenants 1──* email_outbox              (idempotency_key, run_id → agent_runs)
tenants 1──* audit_log                 (append-only, general)
```

`tenants` is the only table **without** RLS. It's a directory used to resolve a tenant slug to an id at login (OD-1).

## Tables

### Identity and tenancy (Phase 1)

| Table | Columns | Constraints and indexes |
|---|---|---|
| `tenants` | id, slug, name, created_at | `UNIQUE(slug)` |
| `users` | id, tenant_id, email, password_hash, role, display_name, is_active, created_at | `UNIQUE(tenant_id, lower(email))`; `CHECK(role IN ('buyer','support'))` |

### Commerce (Phase 1)

| Table | Columns | Constraints and indexes |
|---|---|---|
| `orders` | id, tenant_id, order_number, buyer_id, seller_name, status, currency, total_minor, buyer_note *(untrusted)*, placed_at, delivered_at | `UNIQUE(tenant_id, order_number)`; `UNIQUE(id, currency)` (target of the composite FK); `INDEX(tenant_id, buyer_id, placed_at DESC)`; `CHECK(total_minor >= 0)` |
| `order_items` | id, tenant_id, order_id, sku, name, qty, unit_price_minor, currency | `CHECK(qty > 0)`, `CHECK(unit_price_minor >= 0)` |
| `shipments` | id, tenant_id, order_id, carrier, tracking_number, status, eta, last_event_at | `INDEX(order_id)` |
| `shipment_events` | id, tenant_id, shipment_id, occurred_at, status, location, description *(untrusted, carrier-supplied)* | `INDEX(shipment_id, occurred_at DESC)` |
| `refunds` | id, tenant_id, order_id, amount_minor, currency, reason, status, idempotency_key, approval_id, created_by_run_id, requested_by, provider_ref, created_at | `CHECK(amount_minor > 0)`; `UNIQUE(tenant_id, idempotency_key)`; `UNIQUE(approval_id)`; `FK(order_id, currency) → orders(id, currency)`; `CHECK(status IN ('processing','succeeded','failed'))` |

### Conversations and agent runs (Phase 1 skeleton, filled in during Phases 4 and 6)

| Table | Columns | Constraints and indexes |
|---|---|---|
| `conversations` | id, tenant_id, user_id, title, summary, summary_through_message_id, created_at, updated_at | `INDEX(tenant_id, user_id, updated_at DESC)` |
| `messages` | id, tenant_id, conversation_id, role, content, run_id, created_at | `INDEX(conversation_id, created_at)`; `CHECK(role IN ('user','assistant','notice'))` |
| `agent_runs` | id, tenant_id, conversation_id, principal_user_id, route, status, stop_reason, config_version, model, iteration, tokens_in, tokens_out, cost_micros, deadline_at, lease_owner, lease_expires_at, checkpoint (JSONB), checkpoint_seq, request_idempotency_key, created_at, updated_at | `CHECK(status IN ('queued','running','awaiting_approval','completed','failed','cancelled'))`; `UNIQUE(tenant_id, principal_user_id, request_idempotency_key)`; `INDEX(status, lease_expires_at)` |
| `agent_steps` | id, tenant_id, run_id, seq, kind, call_id, tool_name, args (JSONB), args_hash, output_items (JSONB, llm_call only, verbatim), result (JSONB), usage (JSONB), status, idempotency_key, error_code, latency_ms, started_at, finished_at | `UNIQUE(run_id, seq)`; `UNIQUE(run_id, call_id)` where `call_id IS NOT NULL`; `CHECK(kind IN ('llm_call','tool_call'))` |

**Stop reasons:** `final_answer`, `max_iterations`, `token_budget`, `cost_budget`, `deadline`, `duplicate_calls`, `cancelled`, `error`.

### Approvals and audit (Phase 1 skeleton, Phase 7 behaviour)

| Table | Columns | Constraints and indexes |
|---|---|---|
| `approvals` | id, tenant_id, run_id, step_id, call_id, tool_name, args (JSONB), args_hash, status, requested_by, decided_by, decided_at, decision_reason, expires_at, consumed_at, created_at | `UNIQUE(run_id, call_id)`; **`CHECK(decided_by IS NULL OR decided_by <> requested_by)`** (maker-checker); `CHECK(status IN ('pending','approved','rejected','expired','consumed'))`; `INDEX(tenant_id, status, created_at)`; OD-5: a partial unique index allowing one pending refund approval per order |
| `approval_audit` | id, tenant_id, approval_id, actor_id, action, details (JSONB), at | Append-only. The runtime role has no `UPDATE` or `DELETE` grant. |
| `audit_log` | id, tenant_id, actor_id, action, target_type, target_id, details (JSONB), at | Append-only |

### Memory, RAG and outbox (Phases 3 and 6)

| Table | Columns | Constraints and indexes |
|---|---|---|
| `memories` | id, tenant_id, user_id, kind, content, embedding vector(1536), source_run_id, created_at, superseded_by | HNSW on `embedding`; `INDEX(tenant_id, user_id)` |
| `policy_documents` | id, tenant_id, slug, title, version, effective_from, content_sha256, created_at | `UNIQUE(tenant_id, slug, version)` |
| `policy_chunks` | id, tenant_id, document_id, ordinal, content, embedding vector(1536), tsv (generated `tsvector`) | HNSW on `embedding`; GIN on `tsv`; `UNIQUE(document_id, ordinal)` |
| `email_outbox` | id, tenant_id, idempotency_key, to_address, template, payload (JSONB), status, attempts, next_attempt_at, sent_at, run_id, created_at | `UNIQUE(tenant_id, idempotency_key)`; `INDEX(status, next_attempt_at)` |

## Checkpoint vs. messages vs. steps

| | `messages` | `agent_steps` | `agent_runs.checkpoint` |
|---|---|---|---|
| What | The transcript a human reads | An append-only ledger of every model call and tool call | A snapshot of the loop's machine state |
| Used for | UI, history, summarisation | Audit, evals, idempotency ("did this call already run?") | Resuming a run exactly where it stopped |
| Content | Plain text | Verbatim output items, args, results, usage | The input item list, iteration, budget spent, pending call ids |
