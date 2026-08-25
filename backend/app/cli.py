"""Command-line entry points for the backend. Run via `uv run inbound-triage <command>`."""

import argparse
import asyncio
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory, engine
from app.models import AuditLog, Classification, Extraction, Record, RoutingDecision, Rule, Source
from app.models.enums import RecordStatus
from app.pipeline.audit import write_audit_log
from app.pipeline.batch import BatchSummary, RecordOutcome, compute_stats, run_batch
from app.pipeline.ingest import ingest_json_samples
from app.pipeline.rules import load_seed_rules

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES_PATH = BACKEND_DIR.parent / "seeds" / "inbound_samples.json"
DEFAULT_RULES_PATH = BACKEND_DIR.parent / "seeds" / "rules.json"


async def run_seed(samples_path: Path, rules_path: Path) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Source).where(Source.type == "csv"))
        source = result.scalars().first()
        if source is None:
            source = Source(type="csv", config={"seed_file": samples_path.name}, active=True)
            db.add(source)
            await db.flush()

        outcome = await ingest_json_samples(source, samples_path, db)
        rules_outcome = await load_seed_rules(rules_path, db)
        await db.commit()

    print(f"Seeded {outcome.created} new records, skipped {outcome.skipped} already present")
    print(f"Seeded {rules_outcome.created} new rules, skipped {rules_outcome.skipped} already present")


async def run_rules() -> None:
    async with async_session_factory() as db:
        rules = (
            await db.execute(select(Rule).order_by(Rule.priority.asc()))
        ).scalars().all()

    if not rules:
        print("No rules configured.")
        return

    for rule in rules:
        status = "active" if rule.active else "inactive"
        print(
            f"[{rule.id}] priority={rule.priority}  {status}  {rule.name!r}\n"
            f"    conditions={rule.conditions}\n"
            f"    destination={rule.destination}  requires_review={rule.requires_review}"
        )


def _print_record_line(outcome: RecordOutcome) -> None:
    category = outcome.category or "-"
    confidence = f"{outcome.confidence:.2f}" if outcome.confidence is not None else "-"
    print(f"{outcome.external_ref}\t{category}\t{confidence}\t{outcome.status}")


def _print_error(record: Record, exc: Exception) -> None:
    print(f"\n--- Record {record.id} ({record.external_ref}) failed ---", file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


def _print_summary(total: int, auto_routed: int, needs_review: int, failed: int, pct: float) -> None:
    print()
    print(f"Total processed: {total}")
    print(f"Auto-routed:      {auto_routed}")
    print(f"Needs review:     {needs_review}")
    print(f"Failed:           {failed}")
    print(f"Auto-route rate:  {pct:.1f}%")


async def resolve_record_id(db: AsyncSession, record: str) -> int:
    """Resolves a CLI-supplied record identifier to a primary key. A numeric
    identifier is treated as the primary key directly; anything else is looked up
    as an external_ref. external_ref is only unique per source, so a value that
    matches more than one record is an error asking the caller to use the id."""
    try:
        return int(record)
    except ValueError:
        pass

    result = await db.execute(select(Record.id).where(Record.external_ref == record))
    ids = result.scalars().all()
    if not ids:
        raise ValueError(f"No record found with external_ref {record!r}")
    if len(ids) > 1:
        matches = ", ".join(str(i) for i in ids)
        raise ValueError(
            f"external_ref {record!r} matches multiple records ({matches}); "
            "use the numeric record id to disambiguate"
        )
    return ids[0]


async def run_process(*, record: str | None, limit: int | None, verbose: bool) -> None:
    async with async_session_factory() as db:
        record_id: int | None = None
        if record is not None:
            try:
                record_id = await resolve_record_id(db, record)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(1) from None

        try:
            summary: BatchSummary = await run_batch(
                db,
                record_id=record_id,
                limit=limit,
                on_record=_print_record_line,
                on_error=_print_error if verbose else None,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None

    if summary.total == 0:
        print("No pending records to process.")
        return

    _print_summary(summary.total, summary.auto_routed, summary.needs_review, summary.failed, summary.auto_route_pct)


async def run_stats() -> None:
    async with async_session_factory() as db:
        stats = await compute_stats(db)

    _print_summary(
        stats["total"], stats["auto_routed"], stats["needs_review"], stats["failed"], stats["auto_route_pct"]
    )


async def run_show(record: str) -> None:
    async with async_session_factory() as db:
        try:
            record_id = await resolve_record_id(db, record)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None

        rec = await db.get(Record, record_id)
        if rec is None:
            print(f"Record {record_id} not found", file=sys.stderr)
            raise SystemExit(1)

        classifications = (
            await db.execute(
                select(Classification)
                .where(Classification.record_id == record_id)
                .order_by(Classification.id)
            )
        ).scalars().all()
        extractions = (
            await db.execute(
                select(Extraction).where(Extraction.record_id == record_id).order_by(Extraction.id)
            )
        ).scalars().all()
        routing_decisions = (
            await db.execute(
                select(RoutingDecision)
                .where(RoutingDecision.record_id == record_id)
                .order_by(RoutingDecision.id)
            )
        ).scalars().all()
        audit_entries = (
            await db.execute(
                select(AuditLog).where(AuditLog.record_id == record_id).order_by(AuditLog.id)
            )
        ).scalars().all()

    print(f"Record {rec.id}  (external_ref={rec.external_ref})")
    print(f"Source id:   {rec.source_id}")
    print(f"Status:      {rec.status}")
    print(f"Received at: {rec.received_at}")
    print()
    print("Raw content:")
    print(rec.raw_content)

    print()
    print(f"Classifications ({len(classifications)}):")
    if not classifications:
        print("  (none)")
    for c in classifications:
        print(
            f"  [{c.id}] {c.category}  confidence={c.confidence:.2f}  model={c.model}  "
            f"prompt_version={c.prompt_version}  latency_ms={c.latency_ms}  created_at={c.created_at}"
        )

    print()
    print(f"Extractions ({len(extractions)}):")
    if not extractions:
        print("  (none)")
    for e in extractions:
        print(
            f"  [{e.id}] schema_version={e.schema_version}  confidence={e.confidence:.2f}  "
            f"model={e.model}  created_at={e.created_at}"
        )
        for key, value in e.fields.items():
            print(f"      {key}: {value}")

    print()
    print(f"Routing decisions ({len(routing_decisions)}):")
    if not routing_decisions:
        print("  (none)")
    for r in routing_decisions:
        print(
            f"  [{r.id}] destination={r.destination}  decided_by={r.decided_by}  "
            f"reason={r.reason}  rule_id={r.rule_id}  reviewer_note={r.reviewer_note}  "
            f"created_at={r.created_at}"
        )

    print()
    print(f"Audit log ({len(audit_entries)}):")
    if not audit_entries:
        print("  (none)")
    for a in audit_entries:
        print(f"  [{a.created_at}] {a.actor}  {a.action}")
        if a.before:
            print(f"      before: {a.before}")
        if a.after:
            print(f"      after:  {a.after}")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


async def _check_database() -> CheckResult:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return CheckResult("Database reachable", True)
    except Exception as exc:
        return CheckResult("Database reachable", False, str(exc))


def _migrations_current() -> tuple[bool, str]:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    sync_engine = create_engine(sync_url)
    try:
        with sync_engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        sync_engine.dispose()

    return current == head, f"db revision={current}  head revision={head}"


async def _check_migrations() -> CheckResult:
    try:
        ok, detail = await asyncio.to_thread(_migrations_current)
        return CheckResult("Migrations current", ok, detail)
    except Exception as exc:
        return CheckResult("Migrations current", False, str(exc))


def _check_api_key() -> CheckResult:
    present = bool(settings.anthropic_api_key.strip())
    return CheckResult("ANTHROPIC_API_KEY present", present)


async def _check_live_api_call() -> CheckResult:
    if not settings.anthropic_api_key.strip():
        return CheckResult("Anthropic API reachable", False, "no API key configured")
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        await client.messages.create(
            model=settings.classify_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return CheckResult("Anthropic API reachable", True)
    except Exception as exc:
        return CheckResult("Anthropic API reachable", False, str(exc))


def _check_model_configured() -> CheckResult:
    detail = f"classify_model={settings.classify_model}  extract_model={settings.extract_model}"
    return CheckResult("Configured model", bool(settings.classify_model and settings.extract_model), detail)


async def run_doctor() -> None:
    checks = [
        await _check_database(),
        await _check_migrations(),
        _check_api_key(),
        await _check_live_api_call(),
        _check_model_configured(),
    ]

    all_passed = True
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        line = f"[{status}] {check.name}"
        if check.detail:
            line += f" — {check.detail}"
        print(line)
        all_passed = all_passed and check.passed

    if not all_passed:
        raise SystemExit(1)


async def run_reset_pending() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Record).where(Record.status == RecordStatus.FAILED.value))
        records = result.scalars().all()

        for record in records:
            await write_audit_log(
                db,
                record_id=record.id,
                actor="cli",
                action="reset_to_pending",
                before={"status": record.status},
                after={"status": RecordStatus.PENDING.value},
            )
            record.status = RecordStatus.PENDING.value

        await db.commit()

    print(f"Reset {len(records)} failed record(s) to pending")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="inbound-triage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser(
        "seed", help="Load seed sample records into the database (idempotent on external_ref)"
    )
    seed_parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_SAMPLES_PATH,
        help=f"Path to the seed JSON file (default: {DEFAULT_SAMPLES_PATH})",
    )
    seed_parser.add_argument(
        "--rules-file",
        type=Path,
        default=DEFAULT_RULES_PATH,
        help=f"Path to the seed rules JSON file (default: {DEFAULT_RULES_PATH})",
    )

    process_parser = subparsers.add_parser(
        "process", help="Run pending records through the full pipeline (classify, extract, route)"
    )
    process_group = process_parser.add_mutually_exclusive_group(required=True)
    process_group.add_argument(
        "--limit", type=int, metavar="N", help="Process at most N pending records"
    )
    process_group.add_argument(
        "--all", action="store_true", help="Process every pending record"
    )
    process_group.add_argument(
        "--record",
        "--record-id",
        dest="record",
        metavar="RECORD",
        help="Process a single record by id or external_ref (--record-id is a deprecated alias)",
    )
    process_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full exception and traceback for any record that fails, instead of just marking it failed",
    )

    subparsers.add_parser(
        "stats", help="Print aggregate pipeline numbers from the current DB state"
    )

    subparsers.add_parser(
        "rules", help="List rules currently in the database, ordered by priority"
    )

    show_parser = subparsers.add_parser(
        "show",
        help="Show a record's full detail: classification, extraction, routing decision, audit log",
    )
    show_parser.add_argument("record", metavar="RECORD", help="Record id or external_ref")

    subparsers.add_parser(
        "doctor",
        help="Check DB connectivity, migration status, Anthropic API key/connectivity, and configured model",
    )

    reset_parser = subparsers.add_parser("reset", help="Reset records so they can be reprocessed")
    reset_parser.add_argument(
        "--pending",
        action="store_true",
        required=True,
        help="Set every failed record back to pending",
    )

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(run_seed(args.file, args.rules_file))
    elif args.command == "process":
        asyncio.run(run_process(record=args.record, limit=args.limit, verbose=args.verbose))
    elif args.command == "stats":
        asyncio.run(run_stats())
    elif args.command == "rules":
        asyncio.run(run_rules())
    elif args.command == "show":
        asyncio.run(run_show(args.record))
    elif args.command == "doctor":
        asyncio.run(run_doctor())
    elif args.command == "reset":
        asyncio.run(run_reset_pending())


if __name__ == "__main__":
    main()
