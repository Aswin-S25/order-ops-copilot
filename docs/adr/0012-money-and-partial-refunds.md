# ADR-0012: Money in minor units with currency; partial refunds

- **Status:** Accepted, 2026-11-21

## Context
Floats corrupt money. The marketplace starts in INR but must not hard-code a currency. Refunds can be partial.

## Decision
- Every monetary value is stored as `amount_minor BIGINT` + `currency CHAR(3)` (INR initially, minor unit paise).
- Partial and full refunds are allowed. `refundable_remainder` is computed on the server from the order total minus processing and succeeded refunds.
- The model may propose an amount, and the gate rejects anything over the remainder.
- The refund currency must match the order (a composite FK to `orders(id, currency)`).
- Concurrent refunds on one order are serialised with `SELECT … FOR UPDATE` on the order row.

## Consequences
- Adding currencies later needs no schema change. Formatting is handled at the edges.
- The LLM never does money arithmetic that matters.
