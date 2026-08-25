"""The one wrapper around the Anthropic SDK. Every LLM call in this codebase — from
classify.py or extract.py — goes through call_structured() here. Never call the SDK
directly from a router or pipeline module; this is what keeps model/prompt_version/
latency_ms/raw_response capture consistent, and what makes the whole thing mockable
in tests without hitting the network.
"""

import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


@dataclass
class LLMCallResult(Generic[T]):
    parsed: T
    raw_response: dict[str, Any]
    latency_ms: int


async def call_structured(
    *,
    model: str,
    system: str,
    user_message: str,
    response_model: type[T],
    tool_name: str = "emit_result",
) -> LLMCallResult[T]:
    """Force the model to respond via a single tool call whose input schema mirrors
    `response_model`, then validate the tool input against it."""
    client = _get_client()
    tool_schema = response_model.model_json_schema()
    tool_schema.pop("title", None)

    start = time.monotonic()
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        tools=[
            {
                "name": tool_name,
                "description": f"Emit the {response_model.__name__} result.",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    tool_use_block = next(block for block in response.content if block.type == "tool_use")
    parsed = response_model.model_validate(tool_use_block.input)

    return LLMCallResult(
        parsed=parsed,
        raw_response=response.model_dump(mode="json"),
        latency_ms=latency_ms,
    )
