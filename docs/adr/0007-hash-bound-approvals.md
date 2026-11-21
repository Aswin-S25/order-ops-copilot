# ADR-0007: Hash-bound, single-use, maker-checker approvals

- **Status:** Accepted, 2026-11-21

## Context
Refund creation needs human approval. An approval must authorise exactly one action, not grant a reusable capability, and must not be self-granted.

## Decision
- `args_hash = sha256(tool_name ‖ canonical_json(validated_args) ‖ run_id ‖ call_id)`.
- An approval stores the tool name, args, hash, run, step, call_id, requester, approver, decision, expiry (24h by default) and a consumed timestamp.
- Maker-checker: `decided_by <> requested_by`, enforced in the application **and** by a DB CHECK constraint.
- Decisions take `SELECT … FOR UPDATE` and are written to an append-only `approval_audit`.
- At execution: the hash is recomputed and must match, the approval must be approved, unconsumed and unexpired, and eligibility is re-checked under a lock on the order row. The approval is then marked `consumed`.
- Rejection or expiry is returned to the model as a structured tool error.

## Consequences
- Tampering, replay and self-approval are blocked structurally, not by prompting.
- A changed amount requires a new approval.
