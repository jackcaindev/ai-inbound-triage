"""Seed the demo data: a `csv` source, the messages in inbound_messages.csv (ingested
idempotently, same as any real sync), and the rules in rules.json.

Run from the backend/ directory so its .env / DATABASE_URL apply:
    cd backend && uv run python ../seeds/seed.py
"""

import asyncio
import json
import sys
from pathlib import Path

SEEDS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SEEDS_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models import Rule, Source  # noqa: E402
from app.pipeline.ingest import ingest_csv  # noqa: E402


async def seed() -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Source).where(Source.type == "csv"))
        source = result.scalars().first()
        if source is None:
            source = Source(type="csv", config={}, active=True)
            db.add(source)
            await db.flush()

        ingest_result = await ingest_csv(source, SEEDS_DIR / "inbound_messages.csv", db)
        print(
            f"Ingested {ingest_result.created} new records, "
            f"skipped {ingest_result.skipped} already present"
        )

        rules_data = json.loads((SEEDS_DIR / "rules.json").read_text())
        loaded = 0
        for rule_data in rules_data:
            result = await db.execute(select(Rule).where(Rule.name == rule_data["name"]))
            if result.scalars().first() is not None:
                continue
            db.add(Rule(**rule_data))
            loaded += 1

        await db.commit()
        print(f"Loaded {loaded} new rules ({len(rules_data) - loaded} already present)")


if __name__ == "__main__":
    asyncio.run(seed())
