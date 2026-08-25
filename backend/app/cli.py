"""Command-line entry points for the backend. Run via `uv run inbound-triage <command>`."""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import async_session_factory
from app.models import Source
from app.pipeline.batch import BatchSummary, RecordOutcome, compute_stats, run_batch
from app.pipeline.ingest import ingest_json_samples

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES_PATH = BACKEND_DIR.parent / "seeds" / "inbound_samples.json"


async def run_seed(samples_path: Path) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Source).where(Source.type == "csv"))
        source = result.scalars().first()
        if source is None:
            source = Source(type="csv", config={"seed_file": samples_path.name}, active=True)
            db.add(source)
            await db.flush()

        outcome = await ingest_json_samples(source, samples_path, db)
        await db.commit()

    print(f"Seeded {outcome.created} new records, skipped {outcome.skipped} already present")


def _print_record_line(outcome: RecordOutcome) -> None:
    category = outcome.category or "-"
    confidence = f"{outcome.confidence:.2f}" if outcome.confidence is not None else "-"
    print(f"{outcome.external_ref}\t{category}\t{confidence}\t{outcome.status}")


def _print_summary(total: int, auto_routed: int, needs_review: int, failed: int, pct: float) -> None:
    print()
    print(f"Total processed: {total}")
    print(f"Auto-routed:      {auto_routed}")
    print(f"Needs review:     {needs_review}")
    print(f"Failed:           {failed}")
    print(f"Auto-route rate:  {pct:.1f}%")


async def run_process(*, record_id: int | None, limit: int | None) -> None:
    async with async_session_factory() as db:
        try:
            summary: BatchSummary = await run_batch(
                db, record_id=record_id, limit=limit, on_record=_print_record_line
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
        "--record-id", type=int, metavar="X", help="Process a single record by id"
    )

    subparsers.add_parser(
        "stats", help="Print aggregate pipeline numbers from the current DB state"
    )

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(run_seed(args.file))
    elif args.command == "process":
        asyncio.run(run_process(record_id=args.record_id, limit=args.limit))
    elif args.command == "stats":
        asyncio.run(run_stats())


if __name__ == "__main__":
    main()
