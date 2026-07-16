# Atlas Corporate-Actions Shadow Observer

Status: **SHADOW_RELEASE_CANDIDATE**. Enforcement: **DISABLED**. Acceptance: **PENDING**.

This independent unit reads `atlas.db` via SQLite `mode=ro&immutable=1` plus bounded production log evidence, calls only three corporate-action provider HTTPS endpoints using process environment variable names, and writes exclusively to a separate append-only shadow SQLite database. It has no report, admission, notification, Vault, broker, or production-write authority.

Receipts are exactly `WOULD_CLEAR`, `WOULD_BLOCK`, or `WOULD_DEFER`, unique by trading session, path, and deterministic idempotency key. Provider payloads are not stored; only normalized bounded events and response SHA-256 provenance are retained.

The weekday 16:20 local LaunchAgent invokes one observer cycle then one non-recursive acceptance analysis. Acceptance remains false by schema. Three future complete sessions, every block/defer independently verified, a deterministic seeded sample of at least 20 clears per complete session, path coverage, timing, and production invariance are required before a separate human release decision. This mechanism can never activate enforcement.
