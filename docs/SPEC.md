# Build Spec — Inbound Triage & Routing Workflow

**Working title (internal):** `inbound-triage`
**Portfolio title (public):** AI Inbound Triage — Automated Classification, Extraction & Human Review

---

## 1. What this project exists to prove

This is a portfolio asset first and a piece of software second. Every scope decision below serves one of these four buyer beliefs:

1. **"He can plug AI into the tools I already use."** — Upwork's fastest-growing dev-adjacent category is AI integration (+178% YoY). The demo must read from and write back to a system a normal business already owns, not live in its own silo.
2. **"He handles the case where the model is wrong."** — Confidence scoring and a human review queue, visible in the UI. This is the single most common unspoken objection in AI job posts.
3. **"A non-technical person could actually operate this."** — The review queue is usable by an ops person, and the docs are written for an owner, not an engineer.
4. **"He measures whether it works."** — An eval harness with real numbers. Almost nobody on the platform shows this, and it's your strongest differentiator.

**Anti-goal:** do not build something impressive to engineers and illegible to buyers. If a feature can't be explained to a business owner in one sentence, it belongs in the optional tier or nowhere.

---

## 2. Demo scenario

**Domain: inbound business requests arriving by email.**

Chosen because it's industry-neutral — every buyer has an inbox full of things that need sorting, so they map their own problem onto it without help. Avoid anything domain-specific (freight, pest control, real estate); the whole point is that the nouns are swappable.

The demo processes a stream of mixed inbound messages and, for each one:

- classifies it into a category (new inquiry / support issue / billing question / scheduling request / spam)
- extracts structured fields (contact name, company, requested action, urgency, dates mentioned, dollar amounts mentioned)
- scores its own confidence
- routes it by rule to a destination queue or owner
- writes the result back to the source sheet
- sends anything low-confidence or high-stakes to a human review queue instead of acting

**Re-skinning note:** because category lists and extraction fields are config, not code, you can demo this to a client and say "this becomes your categories in about an hour." Make that literally true — it's a strong sales line.

---

## 3. Architecture

```
Source (Google Sheet / CSV upload / webhook)
        │
        ▼
  Ingestion worker ──► records table (status=pending)
        │
        ▼
  Classification (LLM, structured output)
        │
        ▼
  Extraction (LLM, Pydantic schema per category)
        │
        ▼
  Confidence scoring
        │
        ├── high confidence ──► Rules engine ──► route + write back ──► notify
        │
        └── low confidence ───► Review queue ──► human decision ──► route + write back
                                     │
                                     └──► decision logged as eval example
```

**Stack:** Python 3.12, FastAPI, Pydantic v2, PostgreSQL, SQLAlchemy + Alembic, Anthropic SDK, React + Vite + TypeScript, Tailwind, Docker Compose.

Deliberately _not_ using LangGraph here. This project's job is to show integration and operational judgment; a framework adds a dependency without adding a buyer-legible benefit. Your existing work already covers agent frameworks.

---

## 4. Data model

**`sources`** — a configured input. `id`, `type` (sheet/csv/webhook), `config` (JSONB — sheet ID, range, credentials ref), `active`, `last_synced_at`

**`records`** — one inbound item. `id`, `source_id`, `external_ref` (row ID / message ID, unique per source — this is your idempotency key), `raw_content`, `received_at`, `status` (pending / processing / auto_routed / needs_review / resolved / failed), `created_at`, `updated_at`

**`classifications`** — `id`, `record_id`, `category`, `confidence` (0–1), `model`, `prompt_version`, `raw_response` (JSONB), `latency_ms`, `created_at`

**`extractions`** — `id`, `record_id`, `schema_version`, `fields` (JSONB), `confidence`, `model`, `raw_response`, `created_at`

**`routing_decisions`** — `id`, `record_id`, `rule_id`, `destination`, `decided_by` (system / human), `reviewer_note`, `created_at`

**`rules`** — `id`, `name`, `priority`, `conditions` (JSONB), `destination`, `requires_review` (bool), `active`

**`audit_log`** — `id`, `record_id`, `actor` (system / user email), `action`, `before` (JSONB), `after` (JSONB), `created_at`. Append-only, never updated or deleted.

**`eval_examples`** — `id`, `record_id`, `expected_category`, `expected_fields` (JSONB), `source` (seeded / human_correction), `created_at`

Key design point worth calling out in the write-up: classifications and extractions are **append-only rows keyed to a record**, not columns on the record. Re-running a record with a new prompt version creates a new row, so you can compare prompt versions against each other over the same data. This is what makes the eval harness possible and it's a genuinely senior design decision — put it in the portfolio description.

---

## 5. Pipeline behaviour

### Ingestion

- Poll source on a schedule (APScheduler is fine — don't over-engineer with Celery)
- Idempotent on `(source_id, external_ref)` — re-running never duplicates
- New records land as `pending`

### Classification

- Single LLM call, structured output via Pydantic
- Prompt includes category definitions from config, not hardcoded
- Store `prompt_version` on every row
- Confidence comes from the model being asked to self-report _plus_ a floor rule: if the extracted fields for the chosen category are mostly empty, cap confidence

### Extraction

- Per-category Pydantic schema, selected by the classification result (two-phase: classify, then extract)
- Missing fields are `None`, never invented — say this explicitly in the prompt and test it
- Any field the schema marks required-but-missing forces `needs_review`

### Confidence & routing

- Threshold configurable, default 0.85
- Below threshold → `needs_review`
- Above threshold → evaluate rules in priority order, first match wins
- Rules can independently force review regardless of confidence (e.g. dollar amount over a limit) — demonstrates that guardrails aren't only about model uncertainty

### Human review

- Reviewer sees raw content, model's classification, extracted fields, and confidence
- Can accept, correct, or reject
- **Every correction writes an `eval_examples` row.** This closes the loop: human corrections become the eval set. This is the smartest thing in the build — make sure it's visible in the demo and named in the write-up.

### Write-back

- Result written to source (sheet columns: category, key fields, status, reviewed_by)
- Failures retry with backoff, then mark `failed` and surface in the UI — never fail silently

### Notification

- Email on batch completion with a summary: processed, auto-routed, awaiting review
- Immediate email when a record hits a "high stakes" rule

---

## 6. API surface

```
POST   /sources                     create source config
GET    /sources
POST   /sources/{id}/sync           trigger ingestion now
GET    /records?status=&category=   list with filters
GET    /records/{id}                full detail incl. classification, extraction, audit trail
POST   /records/{id}/review         submit human decision
POST   /records/{id}/reprocess      re-run with current prompt version
GET    /rules  POST /rules  PATCH /rules/{id}
GET    /metrics                     counts by status, avg confidence, review rate, throughput
POST   /evals/run                   run eval set against current prompt version
GET    /evals/runs                  history of eval runs with scores
POST   /webhooks/inbound            generic webhook ingestion
GET    /health                      dependency checks (db, LLM API)
```

---

## 7. Frontend

Four screens. Resist adding a fifth.

**Dashboard** — counts by status, review rate, avg confidence, throughput over time. This is your portfolio thumbnail, so it needs to look good. Real charts, real numbers, no lorem ipsum.

**Review queue** — the money screen. Raw content on the left, model output on the right, editable fields, accept / correct / reject. Keyboard shortcuts. A non-technical person should understand it without training.

**Record detail** — full audit trail as a timeline: received → classified (conf 0.72) → flagged for review → corrected by human → routed → written back. This one screenshot proves the guardrails story better than any paragraph.

**Rules config** — list, edit, reorder by priority. Shows a buyer that logic is configurable without a developer.

Design note: pick a restrained palette and one good typeface. Buyers judge competence on visual polish faster than they judge it on architecture, and most competing portfolios look like unstyled Bootstrap.

---

## 8. Eval harness

This is the differentiator. Budget real time for it.

- Seed 40–60 labelled examples across all categories, including deliberately ambiguous ones
- `POST /evals/run` scores current prompt version: classification accuracy, per-field extraction precision/recall, confidence calibration (do high-confidence predictions actually get accepted by reviewers?)
- Store every run; UI shows a table of runs by prompt version
- **Ship at least two prompt versions** so the UI shows a real before/after improvement

The portfolio line this earns you: "v1 classified at 82%; adding few-shot examples for the two categories the model confused took it to 94%. Here's the eval run that proves it." Almost nobody on Upwork can say that sentence.

---

## 9. Deployment

Must be live at a public URL. A GitHub link alone converts badly — most buyers won't clone anything.

- Railway or Fly.io, Postgres attached
- Seeded demo data on boot, plus a **"Process a sample batch"** button that runs the pipeline live in ~15 seconds so a visitor sees it work without signing up
- No auth wall on the demo. A login screen kills conversion.
- Rate limit the LLM endpoints and cap spend — assume someone will hammer it
- README with a 60-second Loom-style walkthrough link if you can record one

---

## 10. Seed data

Write 60–80 realistic inbound messages by hand or generate and then edit. They must include:

- clear-cut cases in every category
- genuine ambiguity (a billing question that's also a complaint)
- missing information (no contact name, vague request)
- an obvious spam/phishing example
- one very high-dollar request that triggers the review rule

The demo is only convincing if the review queue has interesting things in it. All-green output looks fake.

---

## 11. Build phases

**Phase 1 — Core (must ship).** Data model + migrations, CSV ingestion, classification, extraction, confidence, rules engine, review queue API, seed data. Acceptance: a seeded batch processes end to end, low-confidence records land in review, corrections persist and create eval examples.

**Phase 2 — Interface.** Four screens, wired to real API. Acceptance: a person who has never seen the codebase can process the review queue without instruction.

**Phase 3 — Integration.** Google Sheets read + write-back, scheduled polling, email notifications. Acceptance: editing the sheet causes a new record; processing writes results back to the correct row.

**Phase 4 — Evals.** Harness, two prompt versions, eval history UI. Acceptance: UI shows measurable improvement between versions.

**Phase 5 — Deploy & document.** Live URL, seeded demo, plain-English README, portfolio write-up.

Realistic timing: this is 3–4 focused days with Claude Code, not one. Phases 1–2 alone are demo-able if you want to start sending proposals before it's finished — and you should.

---

## 12. Optional add-ons, by keyword bought

Only build these if proposal feedback says the keyword matters. Each is roughly half a day.

| Add-on                                    | Upwork keywords it earns                          |
| ----------------------------------------- | ------------------------------------------------- |
| Scheduled scraper as an additional source | web scraping, data extraction, browser automation |
| Slack notifications + slash command       | Slack API, chatbot development                    |
| Chat interface to query processed records | chatbot development, RAG, conversational AI       |
| Airtable connector                        | Airtable, no-code integration                     |
| n8n or Make webhook node                  | n8n, Make, Zapier, workflow automation            |
| Twilio SMS alerts                         | Twilio, SMS integration                           |
| Non-technical operator guide (PDF)        | documentation, training, AI enablement            |

That last row is worth more than it looks — training and enablement show up constantly in AI job posts and you currently have no evidence of it. It's also the cheapest item on the list.

---

## 13. Explicit non-goals

- No multi-tenancy, no user accounts, no billing
- No fine-tuning, no vector DB (it isn't a retrieval problem — don't bolt RAG on for keywords)
- No agent framework
- No mobile layout beyond "doesn't break"
- No more than five categories in the demo

---

## 14. Portfolio packaging

When it's done, the write-up needs:

- **Lead image:** dashboard screenshot or the record-detail audit timeline
- **Title framed as a service**, not a repo name
- **~200 words:** the problem, what it does, the two or three decisions that mattered (append-only classification rows, human corrections feeding the eval set, rules that force review independent of confidence), and the eval numbers
- **Live URL first**, GitHub second
- One sentence making the re-skin explicit: categories and extraction fields are configuration, so adapting it to a new business is hours, not weeks

Write it for a business owner. If a sentence needs an engineering background to parse, cut it.
