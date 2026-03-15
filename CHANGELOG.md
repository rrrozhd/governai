# Changelog

## 0.2.2

Release date: 2026-03-15

Highlights:

- Added token-based PyPI publishing fallback through GitHub environment secret `PYPI_API_TOKEN`.
- Included the `LocalRuntime` remote tool return-shape fix shipped after `0.2.1`.

## 0.2.1

Release date: 2026-03-14

Highlights:

- Fixed GitHub Actions PyPI publishing for trusted publisher mode by enabling OIDC `id-token: write`.
- Keeps the contained execution, thread-native run, and durable interrupt changes introduced in `0.2.0`.

## 0.2.0

Release date: 2026-03-14

Highlights:

- Added contained HTTP sandbox execution with `local_dev` and `strict_remote` runtime modes.
- Added per-executor placement controls for tools and agents.
- Added typed remote execution request/response contracts and a first-party FastAPI sandbox worker.
- Added thread-native execution with caller-supplied `thread_id`.
- Added thread-aware run lookup and resume helpers across `Workflow` and `GovernedFlow`.
- Added durable interrupt persistence with in-memory and Redis stores.
- Added top-level `thread_id` propagation to audit events.
- Expanded docs, examples, and regression coverage for containment, threading, and persistence.
