"""Tracked LLM calls with a per-case budget."""

from __future__ import annotations

import os
import time
from typing import Any

from agent.llm import chat
from agent.state import CaseFile

MAX_MODEL_CALLS = 12
# Wall-clock budget for all model calls in one case. A slow or stuck provider
# ends the case with the safe fallback (guards / human review) instead of hanging.
CASE_TIME_BUDGET = float(os.getenv("CASE_TIME_BUDGET") or 300)


class ModelBudgetExceeded(RuntimeError):
    """Raised when a case has used its 12 model-call cap."""


def tracked_chat(
    case: CaseFile,
    *,
    agent: str,
    step: str,
    action: str,
    messages: list,
    lane: str,
    tools: list | None = None,
    detail: str = "",
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call chat() and record the model, or stop if the cap is reached."""
    if case.model_calls >= MAX_MODEL_CALLS:
        raise ModelBudgetExceeded(
            f"Model-call cap of {MAX_MODEL_CALLS} reached; stopping with human_review"
        )
    started = getattr(case, "_model_started", None)
    if started is None:
        started = time.monotonic()
        case._model_started = started  # not a dataclass field, so not serialised
    remaining = CASE_TIME_BUDGET - (time.monotonic() - started)
    if remaining < 15:
        raise RuntimeError(
            f"Case time budget of {CASE_TIME_BUDGET:.0f}s used up before the {agent} step; "
            "the model provider was too slow"
        )
    result = chat(messages, lane=lane, tools=tools, temperature=temperature, timeout=remaining)
    case.model_calls += 1
    model = result.get("model")
    note = result.get("note")
    summary = detail or action
    if note:
        summary = f"{summary} ({note})"
    case.add_trace(step=step, agent=agent, action=action, detail=summary, model=model)
    return result
