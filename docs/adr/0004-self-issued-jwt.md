# ADR-0004: Self-issued JWTs with Argon2, short-lived, no refresh tokens

- **Status:** Accepted, 2026-11-21

## Context
We need authentication for two roles across tenants without depending on an external identity provider.

## Decision
- Passwords are hashed with Argon2id.
- Access tokens are short-lived HS256 JWTs carrying `sub`, `tenant_id`, `role`, `scopes`, `exp`, `iat` and `jti`. The secret comes from the environment.
- There are no refresh tokens initially.
- All issuing and verification lives in `app/auth.py` behind an interface that produces an `AuthContext`, so an external identity provider (Auth0, Keycloak) can replace it later.

## Consequences
- Users log in again when their token expires, which is acceptable for this project.
- Tokens can't be revoked before expiry. That risk is limited by short lifetimes and the `is_active` check on sensitive endpoints.

## Alternatives considered
An external identity provider (more realistic, more setup). Server-side sessions (needs revocation storage).
