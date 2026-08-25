"""Command-line entry points for the backend. Run via `uv run inbound-triage <command>`."""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.db import async_session_factory
from app.models import Source
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

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(run_seed(args.file))


if __name__ == "__main__":
    main()
