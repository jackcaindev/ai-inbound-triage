# AI Inbound Triage

Classify, extract, route, and human-review inbound business requests. Portfolio
project — it must be demo-able by a non-technical visitor at a public URL.

Full build spec: @docs/SPEC.md — read the relevant section before starting any phase.

## Stack

Python 3.12, FastAPI, Pydantic v2, PostgreSQL, SQLAlchemy 2.x, Alembic,
Anthropic SDK, APScheduler. Frontend: React + Vite + TypeScript + Tailwind.
Local dev via Docker Compose. Package management with `uv`.

## Layout

```
backend/app/models/      SQLAlchemy models
backend/app/schemas/     Pydantic request/response + extraction schemas
backend/app/routers/     FastAPI routes, one file per resource
backend/app/pipeline/    ingest, classify, extract, confidence, rules, writeback
backend/app/prompts/     versioned prompt templates, one file per version
backend/app/evals/       eval runner and scoring
backend/tests/
frontend/src/
seeds/                   demo data + labelled eval examples
docs/
```

## Non-negotiables

These are design decisions, not preferences. Do not refactor them away.

- **Append-only inference records.** `classifications` and `extractions` are rows
  keyed to a `record_id`, never columns on `records`. Re-processing creates a new
  row with a new `prompt_version`. This is what makes version comparison possible.
- **Extraction never invents values.** A field not present in the source is `None`.
  Prompt must say so explicitly, and there must be a test asserting it on an input
  with deliberately missing fields.
- **Human corrections feed the eval set.** Every correction submitted through the
  review queue writes an `eval_examples` row with `source='human_correction'`.
- **Idempotent ingestion** on `(source_id, external_ref)`. Re-running a sync never
  duplicates a record.
- **Rules can force review independently of confidence.** A high-confidence record
  can still be routed to human review by rule.
- **Audit log is append-only.** Never update or delete a row in `audit_log`.
- **Failures are visible.** Write-back failures retry with backoff, then mark the
  record `failed` and surface it in the UI. Never swallow an exception.

## Out of scope

No auth, no user accounts, no multi-tenancy, no billing. No LangGraph or other
agent framework. No vector DB or RAG — this is not a retrieval problem. No
fine-tuning. No more than five categories in the demo. If a request seems to need
one of these, stop and ask.

## Conventions

- Type hints everywhere; `from __future__ import annotations` not needed on 3.12
- Async throughout the request path; no sync DB calls in route handlers
- Every LLM call records `model`, `prompt_version`, `latency_ms`, and raw response
- LLM calls go through one wrapper module — never call the SDK directly from a router
- Config via environment variables, parsed into a Pydantic Settings object
- Migrations for every schema change; never edit a migration that has been applied
- Frontend: no component over ~200 lines, no state library, TanStack Query for server state

## Verify before calling a phase done

```bash
cd backend && uv run pytest              # must pass
cd backend && uv run alembic upgrade head # must run clean from empty DB
cd frontend && npm run build             # must build without type errors
```

## Working style

- Use plan mode for anything touching the data model or pipeline stages.
- One phase at a time. Do not build ahead into later phases.
- When the spec and a convenient shortcut conflict, follow the spec and say so.
- Prefer boring, readable code. This repo gets read by prospective clients.
