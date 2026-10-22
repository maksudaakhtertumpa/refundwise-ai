"""Tracked LLM calls with a per-case budget."""

from __future__ import annotations

from typing import Any

from agent.llm import chat
from agent.state import CaseFile

MAX_MODEL_CALLS = 12


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
    result = chat(messages, lane=lane, tools=tools, temperature=temperature)
    case.model_calls += 1
    model = result.get("model")
    note = result.get("note")
    summary = detail or action
    if note:
        summary = f"{summary} ({note})"
    case.add_trace(step=step, agent=agent, action=action, detail=summary, model=model)
    return result
