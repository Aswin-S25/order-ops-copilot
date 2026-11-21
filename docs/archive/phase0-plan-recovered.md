# Order Ops Copilot: Phase 0, Requirements and Architecture

I haven't created any files yet. Once you answer the questions at the end, I'll write the finished design into the repo as `docs/architecture.md`, `docs/adr/`, `docs/api.md` and `docs/PROGRESS.md`. Everything below is a proposal for you to challenge.

---

## 1. Requirements

**Functional requirements:** order lookup, shipment tracking, policy Q&A (RAG), refund eligibility, refunds with human approval, email notifications, multi-step agent tasks, conversations and memory, and streamed progress.

**Non-functional requirements.** These drive almost every design decision:

| NFR | What it forces in the design |
|---|---|
| **Security:** the model is untrusted | Identity comes from the JWT, never from tool arguments. A policy gate sits between the model and every tool. |
| **Zero duplicate side effects** | Idempotency keys, unique constraints and an outbox for email |
| **Durability:** runs survive restarts | A run state machine in Postgres, with checkpoints at step boundaries |
| **Latency:** P95 time to first event < 1.5s | Thin API, an immediate SSE ack, fast paths that skip the agent |
| **Bounded cost** | Token and cost budgets per run, user and tenant |
| **Measurable quality** | Every step persisted, plus an eval harness in CI |

**Actors**

| Actor | Can do |
|---|---|
| Buyer | Read their own orders, shipments and refund eligibility. *Request* a refund (it is approved by staff). Chat. Manage their own memories. |
| Support staff | Read all orders in their tenant. Approve or reject refunds. Send emails to allow-listed destinations. Chat. |
| LLM | **Not a principal.** It proposes tool calls, and the system decides whether they run under the human principal's authority. |
| Worker | A system process that runs work *on behalf of* the principal recorded on the run |

---

## 2. High-level architecture

```
                 ┌──────────────────────────────────────────────────────────────┐
  Client ──HTTP──►  FastAPI Agent API (thin)                                    │
    ▲            │   auth deps · request validation · router · enqueue · SSE    │
    │ SSE        └──────┬──────────────┬───────────────────┬──────────────┬─────┘
    │                   │ fast path    │ enqueue run       │ approvals    │ read events
    │                   ▼              ▼                   ▼              │
    │            ┌────────────┐  ┌───────────┐     ┌──────────────┐       │
    │            │ Business   │  │  Redis    │     │ Approval     │       │
    │            │ services   │  │  queue +  │◄────┤ service      │       │
    │            │ (orders,   │  │  rate lim │     └──────┬───────┘       │
    │            │ shipments, │  │  + event  │◄───────────┼───────────────┘
    │            │ refunds)   │  │  streams  │            │
    │            └─────▲──────┘  └─────┬─────┘            │
    │                  │               │ dequeue          │
    │                  │               ▼                  │
    │                  │   ┌──────────────────────────────┴───────────────────┐
    │                  │   │ Agent Worker                                     │
    │                  │   │  ┌─────────────┐  ┌────────────┐  ┌───────────┐  │
    │                  │   │  │ Loop        │─►│ Context    │─►│ LLM       │──┼──► OpenAI API
    │                  │   │  │ controller  │  │ builder    │  │ gateway   │  │
    │                  │   │  └──────┬──────┘  └────────────┘  └───────────┘  │
    │                  │   │         │ tool calls                             │
    │                  │   │  ┌──────▼──────┐  ┌────────────┐                 │
    │                  └───┼──┤ Tool        │◄─┤ Policy     │                 │
    │                      │  │ executor +  │  │ gate       │                 │
    │                      │  │ registry    │  └────────────┘                 │
    │                      │  └──────┬──────┘                                 │
    │                      └─────────┼────────────────────────────────────────┘
    │                                ▼
    │            ┌──────────────────────────────────────────────┐   ┌──────────────┐
    └────────────┤ PostgreSQL + pgvector                        │   │ Mock carrier │
                 │ business data · runs/steps/checkpoints ·     │   │ Email outbox │
                 │ approvals · memories · policy chunks · audit │   │ dispatcher   │
                 └──────────────────────────────────────────────┘   └──────────────┘
```

**Rule 1: the API never runs the agent loop.** The API authenticates the request, writes a `run` row, enqueues it and returns `run_id`. The worker owns execution, so a deploy that restarts the API doesn't kill in-flight runs.

**Rule 2: Postgres is the source of truth and Redis is disposable.** If Redis is wiped, runs can be re-enqueued from Postgres (`status IN ('queued','running')` with a stale heartbeat). If Postgres is lost, everything is lost. That asymmetry is deliberate.

---

## 3. Component responsibilities

| Component | Owns | Must NOT do |
|---|---|---|
| **API layer** (`app/api.py`) | HTTP, auth dependencies, input validation, enqueueing, SSE fan-out | Call OpenAI or run tools |
| **Auth** (`app/auth.py`) | JWT verification and building an `AuthContext(user_id, tenant_id, role, scopes)` | Trust any identity that comes from a request body |
| **Router** (`agent/router.py`) | Sending a request to a fast path or to the agent | Execute side effects |
| **Planner** (`agent/planner.py`) | Producing an explicit plan for multi-step dependent tasks | Bypass the policy gate |
| **Loop controller** (`agent/loop.py`) | Iterations, stop conditions, budgets, deadline, checkpoints | Know business rules |
| **Context builder** (`agent/context.py`) | Assembling the system prompt, history, summary, memories and delimited untrusted content | Include another user's data |
| **LLM gateway** (`agent/llm_gateway.py`) | OpenAI calls, retries and backoff, timeouts, usage and cost accounting | Contain any agent logic |
| **Tool registry and executor** (`tools/registry.py`) | Schemas, validation, timeouts, parallel reads, structured errors | Decide authorization alone |
| **Policy gate** (`agent/policy.py`) | Scope checks, ownership, approval requirements, egress allow-list, rate limits | Be skippable |
| **Approval service** (`app/approvals.py`) | Approval lifecycle, hash binding, expiry, audit | Execute the tool itself (the worker does that on resume) |
| **Memory service** (`agent/memory.py`) | User-scoped memory writes and reads, summarisation | Read across user or tenant boundaries |
| **RAG retriever** (`tools/policies_rag.py`) | Chunking, embeddings, pgvector search | Treat document text as instructions |
| **Worker** (`worker/`) | Dequeueing, heartbeats, concurrency limits, graceful shutdown, recovery | Hold a run while waiting for a human |

---

## 4. End-to-end request lifecycle

Example: a buyer writes *"My order #1042 hasn't arrived, can I get a refund?"*

```
 1. POST /conversations/{cid}/messages     (Bearer JWT)
 2. Auth dependency → AuthContext{user=u7, tenant=t1, role=buyer, scopes=[...]}
 3. Persist the user message (tx). Router classifies → "agent" (multi-step: shipment + eligibility)
 4. Insert agent_run(status=queued, principal=u7, config_version=v3, budgets) → XADD to queue
 5. Return 202 {run_id}. Client opens GET /runs/{run_id}/events (SSE)
 6. Worker claims the run → status=running, heartbeat → emits run.started   ◄── time to first event
 7. Loop iteration 1:
      context builder → [system, summary, memories, history, user msg]
      LLM gateway → OpenAI(tools=[schemas the *buyer* may use])
      model returns function calls: get_order(1042), get_shipment(1042)
      policy gate: scopes OK, ownership OK (order.buyer_id == u7, tenant == t1)
      both are read-only → executed in parallel → results persisted as agent_steps
      checkpoint written
 8. Loop iteration 2: model calls get_refund_eligibility(1042) → eligible, max 49.99
 9. Loop iteration 3: model calls create_refund(order 1042, amount 49.99, reason "not delivered")
      policy gate: requires approval → approval row created → run PAUSED (see §6)
10. SSE: approval.required → the client shows "Waiting for support approval"
11. ... staff approves ... the worker resumes, executes the refund, and the model writes the final answer
12. Final assistant message persisted, run status=completed, stop_reason=final_answer, SSE run.completed
```

**Synchronous vs. agent-driven workflows**

| Synchronous (no agent loop) | Agent-driven |
|---|---|
| `GET /orders/{id}` and other plain REST reads | Open-ended or multi-step requests |
| Fast path: "where is order 1042?" → a template or one LLM call | Requests that need tool chaining (shipment → eligibility → refund) |
| Approve / reject endpoints | Anything that may cause side effects |
| Policy Q&A fast path (retrieve → one grounded answer) | Ambiguous intent |

---

## 5. How OpenAI tool calling connects to our backend tools

This is the part people most often misunderstand. **The model never executes anything.** It returns a structured *request* to call a function. Our code decides whether to honour it.

```
Our registry                     Sent to OpenAI                   Returned by OpenAI
─────────────                    ──────────────                   ──────────────────
ToolSpec(                        {"type":"function",              function_call {
  name="get_order",       ──►     "name":"get_order",               call_id: "call_abc",
  args=GetOrderArgs,              "description": "...",             name: "get_order",
  scopes={"orders:read"},         "parameters": <JSON Schema        arguments: '{"order_id":1042}'
  side_effect=False,               from GetOrderArgs>,            }
  timeout=3s,                     "strict": true}
  requires_approval=False,
  fn=get_order_impl)
                                                                         │
             ┌───────────────────────────────────────────────────────────┘
             ▼
  1. Parse the JSON string       → it can be malformed, so handle that as a structured error
  2. GetOrderArgs.model_validate → Pydantic is the real validator, not the JSON schema
  3. Policy gate(AuthContext, spec, args)
  4. Execute fn(ctx: ToolContext, args) with a timeout
  5. Send back {"type":"function_call_output", "call_id":"call_abc", "output": <JSON>}
```

Key design points:

- **The `ToolContext` carries identity, and the argument schema never does.** `GetOrderArgs` has `order_id` and nothing else, with no `user_id` and no `tenant_id`. The implementation queries `WHERE id = :order_id AND tenant_id = :ctx.tenant_id AND (buyer_id = :ctx.user_id OR ctx.role = 'staff')`. The model can supply any order ID it likes, and it still can't see an order the human couldn't see.
- **The `call_id` is the join key.** Every tool output must reference the exact call it answers, or the API rejects the next request. We persist `call_id` on each `agent_step`, and that is what makes resume possible.
- **Errors are results, not exceptions.** A failed tool returns `{"ok": false, "error": {"code": "NOT_FOUND", "message": ..., "retryable": false}}` to the model, so it can recover or explain. Only infrastructure failures escape the loop.
- **Tool exposure is filtered per principal.** A buyer's request never even *sees* staff-only tool schemas. That is defence in depth: the gate would block those calls anyway.

---

## 6. How a refund approval pauses and resumes a run

This is the most important flow in the system. The core insight is that **pausing is not waiting.** No thread or worker slot blocks while a human decides, which could take hours. The run is serialised to Postgres and the worker moves on.

```
WORKER (iteration N)                                      DB state
────────────────────                                      ────────
model → create_refund(order_id=1042, amount_minor=4999, reason="not_delivered")
  │
  ├─ validate args (Pydantic)
  ├─ gate: scope refunds:request ✓  ownership ✓  eligibility ✓ (amount ≤ refundable)
  ├─ spec.requires_approval → True
  ├─ canonical = canonical_json(validated_args)        # sorted keys, normalised types
  ├─ args_hash = sha256(tool_name ‖ canonical ‖ run_id ‖ call_id)
  │
  └─ ONE TRANSACTION:
       INSERT approvals(run_id, call_id, tool_name, args, args_hash,      approval: pending
                        requested_by=u7, tenant=t1, expires_at=now+24h)
       UPDATE agent_steps SET status='awaiting_approval'                  step: awaiting_approval
       UPDATE agent_runs  SET status='awaiting_approval', checkpoint=...  run: awaiting_approval
  emit SSE approval.required → worker releases the run (ack the job)

STAFF: POST /approvals/{id}/approve
  ONE TRANSACTION:
    SELECT ... FOR UPDATE                      # prevents a double-approve race
    check: status=pending, not expired, same tenant, approver has refunds:approve,
           approver ≠ requester (separation of duties)
    UPDATE approvals SET status='approved', decided_by=s2, decided_at=now
    INSERT approval_audit(...)
  enqueue resume job(run_id)

WORKER (resume)
  load the checkpoint → the model-input items, up to and including the function_call(call_id)
  re-load the approval → recompute the hash from the stored step args → must match
  re-check eligibility NOW                     # time-of-check vs. time-of-use: state may have changed
  execute create_refund with idempotency_key = hash(run_id, call_id)
     → INSERT refunds ... ON CONFLICT (idempotency_key) DO NOTHING / return existing
  append function_call_output(call_id, {"ok":true,"refund_id":...})
  continue the loop → the model writes "Your refund of $49.99 was approved..."
```

**If the request is rejected or expires,** the tool output becomes `{"ok": false, "error": {"code": "APPROVAL_REJECTED", ...}}` and the model explains that to the user. The run still finishes with an explicit stop reason.

**Why bind the approval to a hash?** If the model later calls `create_refund` with `amount_minor=99999`, the hash differs, so the existing approval doesn't authorise it. An approval authorises *one exact action*, not a capability.

**Why does a crash at any point not duplicate the refund?** The step status, the idempotency key and the `UNIQUE(idempotency_key)` constraint together make the execution step safe to retry. If the worker dies after the INSERT but before recording the step result, re-execution hits the conflict and returns the existing refund.

**Email uses the outbox pattern.** `send_email` writes an `email_outbox` row (with a unique idempotency key) in the same transaction as the step. A separate dispatcher delivers it. "Did we send it?" is then a database fact, not a guess.

---

## 7. Database entities and relationships

```
tenants 1──* users (role: buyer|staff, email, password_hash)
tenants 1──* orders *──1 users(buyer)
                 orders 1──* order_items
                 orders 1──* shipments 1──* shipment_events
                 orders 1──* refunds ──0..1 approvals
                                    └── created_by_run ──► agent_runs

users 1──* conversations 1──* messages
           conversations 1──* agent_runs (principal_user_id, status, stop_reason,
                                          config_version, tokens_in/out, cost_micros,
                                          deadline_at, heartbeat_at, checkpoint jsonb)
                                    agent_runs 1──* agent_steps (seq, kind: llm|tool,
                                          call_id, tool_name, args, result, status,
                                          latency_ms, tokens, error_code)
                                    agent_runs 1──* approvals (call_id, tool_name, args,
                                          args_hash, status, requested_by, decided_by,
                                          expires_at) 1──* approval_audit
users 1──* memories (tenant_id, user_id, content, embedding vector, source_run_id,
                     created_at, superseded_by)
tenants 1──* policy_documents 1──* policy_chunks (embedding vector)
email_outbox (idempotency_key UNIQUE, to, template, status, attempts)
audit_log (actor, action, target, tenant_id, at)
```

Constraints and indexes I'm planning:

- `tenant_id` goes on **every** tenant-owned table, including child tables, even where it's redundant. Denormalising it means every query can filter on tenant without a join, and it makes Row-Level Security possible (Question 1).
- `orders (tenant_id, buyer_id, placed_at DESC)` serves `list_recent_orders`.
- `agent_steps UNIQUE (run_id, seq)` and `UNIQUE (run_id, call_id)` stop the same step being recorded twice.
- `refunds UNIQUE (idempotency_key)`, plus `CHECK (amount_minor > 0)`.
- `approvals UNIQUE (run_id, call_id)` means one approval per proposed action.
- Money is stored as integer minor units plus a currency code, never floats.
- `memories` gets an HNSW index on the embedding and is always filtered by `(tenant_id, user_id)` first.
- **Checkpoint vs. messages:** `messages` is the human-readable transcript. `checkpoint` is the *exact model-input state* at a step boundary: items, iteration count, budget spent and pending calls. They will diverge once summarisation exists.

---

## 8. API specification (draft)

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/auth/login` | public | Returns a JWT (depends on Question 2) |
| GET | `/auth/me` | any | |
| GET | `/orders`, `/orders/{id}` | buyer (own), staff (tenant) | Plain REST, no LLM |
| GET | `/orders/{id}/shipment` | same | |
| GET | `/orders/{id}/refund-eligibility` | same | |
| POST | `/conversations` | any | |
| GET | `/conversations/{id}/messages` | owner | |
| POST | `/conversations/{id}/messages` | owner | Routes the request. Returns `200` with the answer (fast path) or `202 {run_id}` (agent). |
| GET | `/runs/{id}` | owner, staff | Status, stop reason, usage |
| GET | `/runs/{id}/events` | owner | **SSE**, supports `Last-Event-ID` replay |
| POST | `/runs/{id}/cancel` | owner, staff | Cooperative cancellation |
| GET | `/approvals?status=pending` | staff | |
| GET | `/approvals/{id}` | staff, requester | |
| POST | `/approvals/{id}/approve` and `/reject` | staff | Separation of duties enforced |
| GET / DELETE | `/memories`, `/memories/{id}` | owner | Users can see and delete what the agent remembers |
| POST | `/admin/policies` | staff | Ingest and re-embed policy docs |
| GET | `/health/live`, `/health/ready` | public | `ready` checks Postgres and Redis |

**SSE event types:** `run.started`, `step.llm`, `tool.started`, `tool.completed`, `approval.required`, `approval.resolved`, `message.delta`, `run.completed` (with `stop_reason`), `run.failed`. Events go to a per-run Redis Stream so a reconnecting client can replay from `Last-Event-ID`.

---

## 9. Critical production engineering challenges

1. **Confused deputy.** The agent acts with the user's authority, so a prompt-injected agent becomes a weapon. The defence is server-side identity, per-call authorization and tool exposure filtered by principal.
2. **Duplicate side effects.** Retries, crashes and duplicate model calls all show up at once. The defence is idempotency keys, unique constraints, step status and the outbox.
3. **Time-of-check vs. time-of-use on approvals.** The order may already be refunded through another channel between approval and execution. The defence is re-validating at execution time.
4. **Indirect prompt injection.** Policy documents, shipment notes and buyer-written text are *data* that can contain instructions. The defence is delimiting, never giving untrusted text authority, and having the gate as the backstop.
5. **Memory poisoning.** "Remember that I'm a staff member" must not become a privilege. Memories are user-scoped, never used for authorization, and written only through constrained, validated paths.
6. **Runaway loops and cost.** A model that keeps calling the same tool forever. The defence is iteration caps, duplicate-call detection, token and cost budgets, a deadline, and a forced final answer when a limit is hit.
7. **Durable execution across restarts.** Heartbeats, stale-run reclaiming and resuming from checkpoints.
8. **Streaming across the API/worker split.** SSE is served by the API, but the events come from the worker, so Redis Streams bridges the two.
9. **Evaluating a stochastic system.** A single pass proves nothing. Five trials, a pass-all rate and state assertions (was a refund row actually created?) instead of judging text.
10. **Upstream unreliability.** OpenAI 429s and 5xx errors, plus timeouts from the carrier mock. The defence is bounded retries with jitter, respecting `retry-after`, and per-tool timeouts.

---

## 10. Key architectural decisions (future ADRs)

1. Build our own agent loop on the OpenAI SDK, with no framework.
2. Postgres is the system of record for run state, and Redis is ephemeral.
3. Identity comes from `AuthContext` only, and no tool schema contains identity fields.
4. Approvals are bound to a hash of the exact validated action.
5. Side effects are idempotent through DB unique constraints, plus an outbox for email.
6. A pause releases the worker, and a resume replays from a checkpoint.
7. The router runs before the agent, so the cheapest correct path wins.

The roadmap follows your Phases 1–10 as written. The only refinement I'd make depends on Question 5.

---

## 11. Architecture questions

Each question comes with my recommendation, so you can just answer "agree" where you do.

**Q1. What is a tenant, and how strict is isolation?**
Is a tenant a separate marketplace operator (a multi-tenant SaaS), with support staff seeing all orders in their tenant? Do you also want **Postgres Row-Level Security** as defence in depth on top of query filtering?
*Recommendation:* tenant = marketplace operator; staff are tenant-wide; RLS is added in Phase 2 using a `SET LOCAL app.tenant_id` per transaction. It adds complexity, but it's the strongest guarantee against cross-tenant leaks.

**Q2. Should we issue tokens ourselves or use an external identity provider?**
*Recommendation:* self-issued JWTs (argon2 password hashing, short-lived access tokens, no refresh tokens initially), with verification isolated in one module so swapping in Auth0 or Keycloak later only changes that module.

**Q3. Which OpenAI API surface should we use?**
The **Responses API** is OpenAI's current recommended interface. Chat Completions is older but more widely documented. The Responses API can also store conversation state server-side (`previous_response_id`).
*Recommendation:* use the Responses API with `store=false` and replay the full input from our own checkpoint every time. Server-side state would undermine our recovery, audit and eval story, because the source of truth would live outside our database.

**Q4. What are the approval semantics?**
- Can a staff member approve a refund that their *own* agent run proposed, or must a different staff member approve it (maker-checker)?
- Are refunds full-order only, or can they be partial or per-item?
- Is there a single currency?

*Recommendation:* enforce maker-checker (approver ≠ requester), allow partial refunds capped at the refundable remainder computed by the server, and use a single currency (stored with a currency column for later).

**Q5. When should the worker and queue arrive?**
Phase 9 introduces Redis workers, but Phases 4–8 need durable runs, pause and resume, and SSE. I'd rather not build an in-process version and then rewrite it.
*Recommendation:* introduce a **minimal** worker on raw Redis Streams consumer groups (`XREADGROUP`/`XAUTOCLAIM`, no Celery, RQ or arq) in Phase 4. Phase 9 then hardens it with concurrency limits, shared rate limiting, budgets, graceful shutdown and load tests.

**Q6. Should there be a client UI?**
*Recommendation:* API-first, plus a single static HTML page (no build step) that shows SSE events and has an approval inbox. That's enough to demo the pause and resume visually without turning this into a frontend project. The alternative is to use curl and pytest only.

**Housekeeping:** I'll create the repo at `~/order-ops-copilot` unless you prefer another location.

Once you answer, I'll finalise the design docs and the progress file, then propose the Phase 1 task breakdown.