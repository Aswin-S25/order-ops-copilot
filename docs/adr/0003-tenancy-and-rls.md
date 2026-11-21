# ADR-0003: Tenant = marketplace operator; isolation via app filters plus RLS

- **Status:** Accepted, 2026-11-21

## Context
Multiple marketplace operators share one database. A single missing `WHERE tenant_id = …` in application code would leak data across tenants. Agent-driven queries make that kind of mistake more likely.

## Decision
- A tenant is a marketplace operator. Support staff see every order in their tenant. Buyers see only their own orders (enforced in the services).
- Every tenant-owned table carries `tenant_id` and has `ENABLE` + `FORCE ROW LEVEL SECURITY` with a policy comparing against `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
- Each transaction sets its context with `set_config('app.tenant_id', :tid, true)` (the parameterisable `SET LOCAL`).
- The runtime role `app_user` is `NOSUPERUSER NOBYPASSRLS` and owns no tables. `app_owner` runs migrations.
- Workers set the tenant context from the job's `tenant_id` for every transaction.
- The application also filters on `tenant_id` explicitly (defence in depth).

## Consequences
- Fail closed: no context means zero rows and failed writes.
- Login and cross-tenant system jobs need special handling (open decisions OD-1 and OD-2).
- Tests must connect as `app_user`. Testing as a superuser would silently bypass RLS.
- Filtered ANN search over pgvector needs attention to recall.

## Alternatives considered
App-layer filtering only (simpler, but no backstop). A schema per tenant (strong isolation, but migrations and pooling get painful). A database per tenant (operationally heavy).
