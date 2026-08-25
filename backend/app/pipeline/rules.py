import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Rule
from app.schemas.rules import Condition, condition_matches


@dataclass
class RuleOutcome:
    matched_rule: Rule | None
    destination: str
    requires_review: bool


@dataclass
class RuleSeedResult:
    created: int
    skipped: int


async def load_seed_rules(rules_path: str | Path, db: AsyncSession) -> RuleSeedResult:
    """Loads seeds/rules.json into the rules table. Idempotent on rule name — an
    existing rule with that name is left untouched rather than overwritten, since
    rules are mutable config a user may have already edited in place. Re-running
    seed only ever adds rules that aren't there yet."""
    entries = json.loads(Path(rules_path).read_text(encoding="utf-8"))

    created = 0
    skipped = 0
    for entry in entries:
        existing = (
            await db.execute(select(Rule).where(Rule.name == entry["name"]))
        ).scalars().first()
        if existing is not None:
            skipped += 1
            continue

        db.add(
            Rule(
                name=entry["name"],
                priority=entry["priority"],
                conditions=entry["conditions"],
                destination=entry["destination"],
                requires_review=entry["requires_review"],
                active=entry["active"],
            )
        )
        created += 1

    await db.flush()
    return RuleSeedResult(created=created, skipped=skipped)


async def evaluate_rules(category: str, fields: dict[str, Any], db: AsyncSession) -> RuleOutcome:
    """Loads active rules ordered by priority ascending; first rule whose conditions
    all match wins. A matched rule can force requires_review independently of
    confidence — that's evaluated by the caller (process.py) regardless of how high
    confidence already was. If no rule matches, destination defaults to the category
    name and nothing is forced."""
    result = await db.execute(
        select(Rule).where(Rule.active.is_(True)).order_by(Rule.priority.asc())
    )
    rules = result.scalars().all()

    for rule in rules:
        conditions = [Condition.model_validate(c) for c in rule.conditions]
        if conditions and all(condition_matches(c, category, fields) for c in conditions):
            return RuleOutcome(
                matched_rule=rule, destination=rule.destination, requires_review=rule.requires_review
            )

    return RuleOutcome(matched_rule=None, destination=category, requires_review=False)
