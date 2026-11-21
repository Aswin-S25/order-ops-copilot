# Order Ops Copilot: Architecture

**Status:** Accepted. Phase 0 was signed off on 2026-11-21, and all open decisions (OD-1 to OD-10) were accepted as recommended.
**Based on:** [archive/phase0-plan-recovered.md](archive/phase0-plan-recovered.md) and the decisions made on 2026-11-21 (see [adr/](adr/)).
**Related documents:** [data-model.md](data-model.md) · [api.md](api.md) · [roadmap.md](roadmap.md) · [PROGRESS.md](PROGRESS.md)

---

## 1. Principles

1. **The model proposes; the server decides.** The LLM is not a principal. Every tool call it emits is untrusted input that goes through validation, authorization and policy checks. A fully prompt-injected model must not be able to do anything the human principal couldn't do.
2. **The API never runs the agent loop.** The API authenticates, persists, enqueues and streams. Workers own durable execution.
3. **PostgreSQL is the source of truth, and Redis is disposable.** Redis carries job delivery and event streams. Everything in Redis can be rebuilt from Postgres.
4. **Tenant isolation is enforced twice.** The application filters on `tenant_id`, and PostgreSQL Row-Level Security enforces it as well. A forgotten `WHERE` clause returns zero rows instead of leaking data.
5. **Every side effect is idempotent and auditable.** We use unique idempotency keys, a transactional outbox for email, and audit tables.
6. **Pausing is not waiting.** A run that needs human approval is serialised to Postgres, and the worker moves on to other work.
7. **The cheapest correct path wins.** A router sends simple requests to deterministic fast paths before anything reaches the agent loop.

---

## 2. Actors and permissions

| Actor | Can do |
|---|---|
| **Buyer** | Read their own orders, shipments and refund eligibility. *Request* refunds, which support staff then approve. Chat. View and delete their own memories. |
| **Support staff** | Read every order in their tenant. Request refunds. Approve or reject refunds requested by *someone else* (maker-checker). Send emails to allow-listed destinations. Chat. Manage policy documents. |
| **LLM** | **Not a principal.** It proposes tool calls, and they run under the authority of the human principal recorded on the run. |
| **Worker** | A system process that acts *on behalf of* the run's principal. It always sets the run's tenant context before touching the database. |

A **tenant** is one marketplace operator. Every user belongs to exactly one tenant.

### Scopes (stored as JWT claims, derived from the user's role)

| Scope | Buyer | Support |
|---|:--:|:--:|
| `orders:read` (buyers: own orders only; support: whole tenant) | ✓ | ✓ |
| `shipments:read` (same ownership rule) | ✓ | ✓ |
| `policies:read` | ✓ | ✓ |
| `refunds:eligibility` | ✓ | ✓ |
| `refunds:request` | ✓ | ✓ |
| `refunds:approve` | | ✓ |
| `email:send` (buyers: only to themselves) | ✓ | ✓ |
| `policies:manage` | | ✓ |

Ownership (whether *this* buyer owns *this* order) is checked in the domain services. Scopes answer "may this role use this capability at all?" Ownership answers "may this user touch this particular row?"

---

## 3. High-level architecture

```
                 ┌──────────────────────────────────────────────────────────────┐
  Browser  ─HTTP─►  FastAPI Agent API (thin)                                    │
  (static  ◄─SSE─┤   auth deps · validation · router · fast paths · enqueue ·   │
  HTML)          │   SSE relay · approvals · static page                        │
                 └──────┬──────────────┬───────────────────┬──────────────┬─────┘
                        │ fast path    │ XADD job          │ approve/     │ XREAD
                        ▼              ▼                   ▼ reject       │ run events
                 ┌────────────┐  ┌──────────────┐  ┌──────────────┐       │
                 │ Domain     │  │ Redis        │  │ Approval     │       │
                 │ services   │  │ jobs stream  │◄─┤ service      │       │
                 │ orders     │  │ (consumer    │  └──────────────┘       │
                 │ shipments  │  │  group)      │                         │
                 │ refunds    │  │ run:{id}:    │◄────────────────────────┘
                 │ email      │  │  events      │
                 │ policies   │  │ rate limits  │
                 └─────▲──────┘  └──────┬───────┘
                       │                │ XREADGROUP / XAUTOCLAIM
                       │                ▼
                       │   ┌──────────────────────────────────────────────────┐
                       │   │ Agent Worker (minimal from Phase 4)              │
                       │   │  lease + heartbeat (Postgres) → loop controller  │
                       │   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
                       │   │  │ Loop       │─►│ Context    │─►│ LLM        │──┼──► OpenAI
                       │   │  │ controller │  │ builder    │  │ gateway    │  │   Responses API
                       │   │  └─────┬──────┘  └────────────┘  └────────────┘  │   (store=false)
                       │   │  ┌─────▼──────┐  ┌────────────┐                  │
                       └───┼──┤ Tool       │◄─┤ Policy     │                  │
                           │  │ executor + │  │ gate       │                  │
                           │  │ registry   │  └────────────┘                  │
                           │  └────────────┘                                  │
                           └───────────────────────┬──────────────────────────┘
                                                   ▼
   ┌───────────────────────────────────────────────────────────┐  ┌───────────────┐
   │ PostgreSQL + pgvector   (RLS on every tenant-owned table) │  │ Mock carrier  │
   │ business data · runs/steps/checkpoints · approvals ·      │  │ (httpx)       │
   │ memories · policy chunks · email outbox · audit           │  │ Outbox        │
   └───────────────────────────────────────────────────────────┘  │ dispatcher →  │
                                                                  │ mock mailer   │
                                                                  └───────────────┘
```

---

## 4. Components

This refines the brief's repository layout. **One addition is justified:** a `services/` package. The REST endpoints and the agent tools both need the same business logic and the same ownership checks. If that logic lived inside `tools/`, the REST API would either duplicate it or depend on the agent layer. So tools are thin adapters over the services.

| Component | Module | Owns | Must NOT |
|---|---|---|---|
| API layer | `app/api.py` (later split into routers) | HTTP, auth dependencies, validation, enqueueing, SSE relay, static page | Call OpenAI, run tools, run the agent loop |
| Auth | `app/auth.py` | Password hashing (Argon2), JWT issue and verify, `AuthContext(user_id, tenant_id, role, scopes)` | Trust any identity taken from a request body or from LLM output |
| Approvals API | `app/approvals.py` | Approval endpoints, maker-checker check, audit | Execute the tool (the worker does that on resume) |
| Events | `app/events.py` | Publishing to the per-run Redis Stream, SSE formatting, `Last-Event-ID` replay | Be the durable record (Postgres steps are) |
| DB session | `db/session.py` | Async engine, a tenant-scoped transaction helper (`set_config('app.tenant_id', …, true)`) | Hand out a session with no tenant context |
| Models / migrations | `db/models.py`, `db/migrations/` | Schema, constraints, RLS policies | — |
| Domain services | `services/*.py` | Orders, shipments, refunds (eligibility, remainder, creation), email outbox, policy retrieval | Know that an LLM exists |
| Router | `agent/router.py` | Choosing a fast path or the agent | Execute side effects |
| Planner | `agent/planner.py` | An explicit plan for multi-step dependent tasks (Phase 5) | Bypass the policy gate |
| Loop controller | `agent/loop.py` | Iterations, stop conditions, budgets, deadline, checkpoints, pause and resume | Contain business rules |
| Context builder | `agent/context.py` | System prompt, history, summary, memories, delimited untrusted content | Include another user's data |
| LLM gateway | `agent/llm_gateway.py` | The **only** importer of `openai`. Retries, timeouts, usage and cost, item serialisation | Contain agent logic |
| Policy gate | `agent/policy.py` | Scope checks, approval requirement, egress allow-list, rate limits, duplicate-call detection | Be skippable |
| Memory | `agent/memory.py` | User-scoped memory reads and writes, summarisation | Read across user or tenant boundaries |
| Tool registry / executor | `tools/registry.py` + `tools/*.py` | `ToolSpec`, schema generation, validation, timeouts, parallel reads, structured errors | Decide authorization alone |
| Worker | `worker/worker.py` | Consumer group, Postgres lease and heartbeat, executing runs, recovery | Hold a run while waiting for a human |
| Rate limits / budgets | `worker/rate_limit.py`, `worker/budgets.py` | Shared Redis token buckets; per-run, per-user and per-tenant token and cost budgets | — |
| Static UI | `app/static/index.html` | Login, chat, live SSE timeline, approval inbox. No build step. | Contain any business logic |
| Evals | `evals/` | Sandbox, cases, runner, failure classifier, reports | — |

---

## 5. End-to-end request lifecycle

Example: a buyer writes *"My order #1042 hasn't arrived, can I get a refund?"*

```
 1. POST /conversations/{cid}/messages   Authorization: Bearer <JWT>   Idempotency-Key: <uuid>
 2. Auth dependency → AuthContext{user=u7, tenant=t1, role=buyer, scopes=[...]}
 3. BEGIN; set_config('app.tenant_id', t1, true)           ← RLS context for this transaction
      insert user message; router classifies → "agent"
      insert agent_run(status=queued, principal=u7, tenant=t1, config_version, model, budgets, deadline)
    COMMIT
 4. XADD jobs {type: start_run, run_id, tenant_id}   (after commit; the reconciler covers a crash between the commit and the XADD)
 5. 202 {run_id}. The client opens GET /runs/{run_id}/events (SSE)
 6. Worker XREADGROUP → claims the lease in Postgres (conditional UPDATE) → status=running
      → XADD run:{id}:events run.started                                      ◄── time to first event
 7. Iteration 1: context builder → input items; LLM gateway → OpenAI (tools filtered to buyer scopes)
      output: function_call get_order(1042), function_call get_shipment(1042)
      persist the llm_call step with its output items VERBATIM
      validate → gate (scopes ✓, ownership ✓) → both are READ → execute in parallel → persist the tool steps
      append function_call_output items → checkpoint
 8. Iteration 2: get_refund_eligibility(1042) → eligible, refundable remainder ₹4,999.00
 9. Iteration 3: create_refund(order 1042, amount_minor=499900, currency=INR, reason=not_delivered)
      gate → requires approval → approval row created, run → awaiting_approval (§7) → XACK, lease released
10. SSE approval.required → the UI shows "Waiting for support approval"
11. A support user approves → resume job → the worker re-validates, executes, continues
12. Final assistant message persisted; run status=completed, stop_reason=final_answer; SSE run.completed
```

**Synchronous vs. agent-driven workflows**

| Synchronous (no agent loop) | Agent-driven (worker) |
|---|---|
| Plain REST reads (`GET /orders/{id}`, …) | Open-ended or multi-step requests |
| Fast path: order status → template or one LLM call | Requests that chain tools (shipment → eligibility → refund) |
| Fast path: policy Q&A → retrieve → one grounded answer | Anything that can cause a side effect |
| Approve / reject endpoints | Ambiguous intent |

Per **OD-3**, fast paths also execute as runs (`route=fast`) on the worker. Every chat message returns `202 {run_id}` and streams over SSE, so there is one client contract.

---

## 6. OpenAI tool calling and Responses API replay

### 6.1 From registry to model and back

```
ToolSpec(name="get_order", args=GetOrderArgs, scopes={"orders:read"},
         side_effect=READ, requires_approval=False, timeout_s=3, fn=get_order)
   │  to_openai_tool() → {"type":"function","name":"get_order","description":...,
   │                      "parameters": <strict JSON Schema>, "strict": true}
   ▼
OpenAI output item: {"type":"function_call","call_id":"call_abc","name":"get_order",
                     "arguments":"{\"order_id\":\"1042\"}"}
   │  1. json.loads              → malformed → structured error back to the model
   │  2. GetOrderArgs.model_validate (Pydantic is the real validator)
   │  3. policy gate(AuthContext, spec, args)
   │  4. fn(ToolContext, args) under asyncio.timeout(spec.timeout_s)
   ▼
{"type":"function_call_output","call_id":"call_abc","output":"{\"ok\":true,...}"}
```

- **No tool argument schema contains identity.** There is no `user_id` or `tenant_id` argument. Identity reaches the tool only through `ToolContext`, which is built from the run's recorded principal.
- **Errors are results.** A tool failure becomes `{"ok": false, "error": {"code", "message", "retryable"}}` for the model. Only infrastructure faults escape the loop.
- **Tool exposure is filtered per principal.** A buyer's request never includes schemas for tools that only support staff may use.

### 6.2 Replay rules (with `store=false`, we own the conversation state)

1. **Persist output items verbatim.** Every response's `output` array is stored as returned, in JSONB on the `llm_call` step. We never rebuild items from parsed fields.
2. **Build the next request** as: the previous input items, then *all* output items of the previous response (reasoning, message and function_call, in their original order), then one `function_call_output` per `call_id`.
3. **Every `function_call` gets exactly one `function_call_output`** before the next request. A paused call is answered on resume. A rejected or expired call is answered with an error output.
4. **Reasoning items.** For reasoning models, request `include=["reasoning.encrypted_content"]` and pass reasoning items back unchanged next to their function calls. With `store=false`, the encrypted content is the only way the model gets its earlier reasoning back. Store it, but never log it.
5. **The model and config are pinned per run.** `agent_runs.config_version` and `model` are fixed when the run is created. A resumed run uses the same model, because we don't assume replayed reasoning items carry over between models.
6. **Summarise only between runs, never within one.** Inside a run, the item list is replayed exactly. Summarisation compresses *conversation history* when the context builder starts a new run.

---

## 7. Refund approval: pause and resume

```
WORKER (iteration N)
model → create_refund(order_id=1042, amount_minor=499900, currency="INR", reason="not_delivered")
  ├─ validate (Pydantic) → gate: scope refunds:request ✓, ownership ✓
  ├─ eligibility: amount ≤ refundable_remainder, currency == order.currency
  ├─ spec.requires_approval → True
  ├─ args_hash = sha256(tool_name ‖ canonical_json(validated_args) ‖ run_id ‖ call_id)
  └─ ONE TRANSACTION (tenant context set):
       INSERT approvals(... status=pending, requested_by=principal, expires_at=now+24h)
       INSERT approval_audit(requested)
       UPDATE agent_steps  SET status='awaiting_approval'
       UPDATE agent_runs   SET status='awaiting_approval', checkpoint=..., lease_owner=NULL
  XADD run.events approval.required → XACK the job

SUPPORT: POST /approvals/{id}/approve      (tenant context from the approver's JWT)
  ONE TRANSACTION:
    SELECT ... FROM approvals WHERE id=:id FOR UPDATE      -- serialises double-clicks and races
    require: status=pending, expires_at > now(), approver has refunds:approve,
             approver != requested_by                       -- maker-checker (also a DB CHECK)
    UPDATE approvals SET status='approved', decided_by, decided_at
    INSERT approval_audit(approved)
    UPDATE agent_runs SET status='queued'
  XADD jobs {type: resume_run, run_id, tenant_id}

WORKER (resume)
  claim lease → load checkpoint (items up to and including function_call c7)
  recompute args_hash from the stored step args → must equal approval.args_hash
  approval.status == approved AND not consumed AND not expired
  ONE TRANSACTION:
    SELECT ... FROM orders WHERE id=:order FOR UPDATE      -- serialises concurrent partial refunds
    recompute refundable_remainder NOW                     -- time of check vs. time of use
    INSERT refunds(..., idempotency_key = sha256(run_id ‖ call_id), approval_id)
       ON CONFLICT (tenant_id, idempotency_key) DO NOTHING → if it conflicts, read the existing row
    UPDATE approvals SET status='consumed'                 -- an approval is single-use
    UPDATE agent_steps SET status='succeeded', result=...
  append function_call_output(c7) → continue the loop → final answer
```

- **Rejection or expiry.** The output for `c7` is `{"ok": false, "error": {"code": "APPROVAL_REJECTED" | "APPROVAL_EXPIRED"}}`. The model explains the outcome, and the run ends with an explicit stop reason. A sweeper expires stale approvals and enqueues the resume.
- **Why hash-bind?** An approval authorises **one exact action**, not a capability. A different amount, order or call produces a different hash.
- **Why no duplicate refund on a crash?** If the worker dies after the refund INSERT commits, the retry hits the unique `idempotency_key` and returns the existing refund. The refund insert and the step update share one transaction, so neither can be committed without the other.
- **Email** uses the same pattern. `send_email` inserts an `email_outbox` row with a unique key in the step's transaction, and the dispatcher delivers it with at-least-once semantics plus dedupe.

---

## 8. Tenant isolation: application filtering plus RLS

- Every tenant-owned table has `tenant_id NOT NULL` (denormalised onto child tables too) and:
  ```
  ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
  ALTER TABLE <t> FORCE  ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON <t>
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
  ```
- **Fail closed.** If no tenant is set, the comparison is `NULL`, so reads return zero rows and writes fail `WITH CHECK`. `NULLIF(…, '')` matters because, once a custom setting has been used in a session, `current_setting(…, true)` returns `''` rather than `NULL` after the transaction ends. Casting `''` to uuid would raise an error.
- **Per transaction, not per connection.** The helper runs `SELECT set_config('app.tenant_id', :tid, true)`. That is the parameterisable form of `SET LOCAL`, which can't take bind parameters. It is cleared at COMMIT or ROLLBACK, so pooled connections can't leak a tenant to the next request.
- **Two database roles.** `app_owner` owns the tables and runs migrations. `app_user`, used at runtime by the API and workers, is `NOSUPERUSER NOBYPASSRLS` and not a table owner. Superusers and owners bypass RLS. `FORCE` covers owners, but not superusers.
- **Workers.** Job payloads carry `(run_id, tenant_id)`. The worker sets that tenant before loading the run. A forged `tenant_id` gets you nothing, because the run isn't visible under the wrong tenant.
- **RLS is tenant-level only.** Buyer ownership is enforced in the services. Putting user-level rules in RLS too would double the complexity for little extra safety.
- **Cross-tenant system jobs** (the reconciler, approval sweeper and outbox dispatcher) use `SECURITY DEFINER` functions that return only `(id, tenant_id)`. The real work then runs in tenant-scoped transactions (**OD-2**).
- **pgvector under RLS.** Tenant filtering happens *after* the ANN index scan, which can lower recall. Queries also filter on `tenant_id` explicitly, and we'll enable pgvector's iterative index scans. This is checked in Phase 3.

---

## 9. Worker and queue model

- **Streams:** `jobs` (consumer group `workers`) carries `start_run`, `resume_run` and `cancel_run`. Each run also has an event stream, `run:{run_id}:events`, with `MAXLEN ~` and a TTL.
- **Delivery is at-least-once.** `XREADGROUP >` reads new jobs. `XAUTOCLAIM` reclaims entries that have been idle longer than `min-idle-time`, which happens when a consumer crashes.
- **Redis decides delivery; Postgres decides ownership.** A worker owns a run only after a conditional `UPDATE agent_runs SET lease_owner=…, lease_expires_at=now()+ttl WHERE id=… AND (lease_owner IS NULL OR lease_expires_at < now()) RETURNING …`. Heartbeats extend the lease. A duplicate delivery that loses the lease race is acknowledged and dropped.
- **`XACK` happens only after the run's state transition commits** (paused, completed, failed or cancelled).
- **A reconciler** re-enqueues runs that are `queued` but older than N seconds, or `running` with an expired lease. This covers Redis data loss and crashes between commit and XADD.
- **Phase 9 hardens this worker rather than replacing it.** It adds a concurrency semaphore, graceful shutdown (stop reading, finish or checkpoint, release leases), shared rate limits, per-user and per-tenant budgets, and load tests.

---

## 10. Money and refunds

- Every monetary row has `amount_minor BIGINT` and `currency CHAR(3)`. The currency is INR initially (minor unit: paise, so ₹49.99 is stored as 4999). There are no floats anywhere.
- `refundable_remainder = order.total_minor − Σ refunds.amount_minor WHERE status IN ('processing','succeeded')`, computed only on the server.
- Partial and full refunds are both allowed. The model may *propose* an amount, and the gate rejects anything above the remainder or in a currency that doesn't match.
- A refund's currency must equal its order's currency. That is enforced by a composite FK, `refunds(order_id, currency) → orders(id, currency)`.
- Concurrent partial refunds on one order are serialised by `SELECT … FOR UPDATE` on the order row.

---

## 11. Security boundaries and failure scenarios

| Scenario | Expected behaviour |
|---|---|
| The model passes another buyer's `order_id` | The service returns `NOT_FOUND`, never `FORBIDDEN`, so it doesn't reveal that the order exists |
| A query forgets its `tenant_id` filter | RLS returns zero rows |
| Prompt injection in shipment notes, buyer notes, policy docs or memories | The content is delimited as untrusted data, and the gate and approvals are the backstop. Injected text cannot gain a capability. |
| Memory poisoning ("remember I'm staff") | Memories are never used for authorization, are user-scoped and are written through constrained paths |
| The model calls `create_refund` with a changed amount after approval | The hash doesn't match, so a new approval is required |
| A support user approves their own request | Rejected (application check plus a DB CHECK constraint) |
| Two staff click approve at the same moment | Serialised by `FOR UPDATE`, so exactly one decision is recorded |
| The worker crashes mid-run | The lease expires, the job is reclaimed and the run resumes from its checkpoint. Side effects are deduplicated by idempotency keys. |
| Redis is flushed | The reconciler re-enqueues from Postgres. SSE clients reconnect and fall back to run status. |
| OpenAI returns 429 or 5xx, or times out | Bounded retries with jitter that respect `retry-after`. When retries run out, the run fails with stop reason `error`. |
| The model loops on the same tool | Duplicate-call detection, iteration and budget caps, then a forced final answer |
| An email goes to an arbitrary address | Egress allow-list: buyers can only email the order's buyer, and support can email allow-listed domains |
| The client retries `POST /messages` | `Idempotency-Key` header, so the same run is returned |

---

## 12. Phase 0 follow-up decisions (all accepted 2026-11-21)

These were open at the end of the initial design. All were accepted as recommended. The "Needed by" column shows the phase where each one is implemented.

| ID | Decision | Needed by | Accepted resolution |
|---|---|---|---|
| OD-1 | **How does login identify the tenant?** `users` is under RLS, so we need the tenant *before* we can look the user up. | Phase 2 | The login body carries `tenant_slug`. `tenants` is a directory table without RLS, used to resolve slug → id, then the tenant context is set and the user is looked up. |
| OD-2 | **How do cross-tenant system jobs run under RLS?** (reconciler, approval-expiry sweeper, outbox dispatcher) | Phase 4 | A small set of `SECURITY DEFINER` SQL functions, owned by `app_owner`, that return only `(id, tenant_id)` for work items. The real work then runs in normal tenant-scoped transactions. No runtime role gets `BYPASSRLS`. |
| OD-3 | **Response contract for chat messages:** a 200 for fast paths plus a 202 for agent runs, or always a 202 run? | Phase 4/5 | Always a 202 plus SSE. Fast paths execute as runs with `route=fast` (often without calling the model). That gives one client contract and one trace and eval format, and every LLM call is accounted for. The cost is one queue hop of a few milliseconds. |
| OD-4 | **SSE authentication from the static page.** The browser's `EventSource` can't send an `Authorization` header. | Phase 4 | Read SSE with `fetch()` and a stream reader so the Bearer header can be sent. Never put JWTs in URLs, because URLs end up in logs. |
| OD-5 | **Do pending approvals reserve refund amount?** | Phase 7 | No reservation, but at most one *pending* refund approval per order (partial unique index). The remainder is re-checked at execution anyway. |
| OD-6 | **Async database access?** | Phase 1 | SQLAlchemy 2.0 async with `asyncpg` in both the API and workers. Alembic runs migrations through an async engine adapter. |
| OD-7 | **Policy corpus and RAG implementation** | Phase 3 | Build a fresh hybrid retriever (pgvector + Postgres full-text search) and carry over the lessons from Policy Copilot. Use 8–12 synthetic INR-marketplace policy documents, including deliberately versioned or conflicting ones. |
| OD-8 | **Eval cost and CI cadence** | Phase 8 | A smoke subset (about 10 cases × 1 trial) on every PR. The full suite (30+ cases × 5 trials) runs nightly and before releases. The runner has a hard cost cap. |
| OD-9 | **Embedding model and dimension** | Phase 3 | Configurable model. The vector dimension is fixed in the schema, so changing it requires a migration and re-embedding. Default: `text-embedding-3-small` (1536). |
| OD-10 | **Primary keys** | Phase 1 | UUID primary keys generated in the application, plus a human-readable `order_number` that is unique per tenant. |
