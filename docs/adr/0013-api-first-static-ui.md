# ADR-0013: API-first with a static HTML demo page

- **Status:** Accepted, 2026-11-21

## Context
Pause and resume, SSE progress and approvals are hard to demonstrate with curl alone, but a frontend build system would distract from the backend goals.

## Decision
The API is the product. A single static `app/static/index.html` (vanilla JS, no build step), served by FastAPI, demonstrates: login, run creation, the live SSE timeline (tool calls and results), approval requests, the approve and reject inbox, pause and resume, and final results. SSE is read with `fetch()` and a stream reader so the Bearer token goes in a header, never in a URL (OD-4).

## Consequences
- The demo stays small and reviewable.
- The UI contains no business logic, and all rules stay on the server.
