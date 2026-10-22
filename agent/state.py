"""Shared case file passed between RefundWise agents."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_REQUESTS_PATH = _ROOT / "input_examples" / "requests.json"


def default_demo_today() -> str:
    """Return the frozen demo date from requests.json, or 2026-10-25."""
    try:
        payload = json.loads(_REQUESTS_PATH.read_text())
        value = payload.get("demo_today")
        if value:
            return str(value)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return "2026-10-25"


@dataclass
class EvidenceItem:
    """One SQL query (or fallback) and the rows it returned."""

    id: str
    source: str
    sql: str
    rows: list[Any]
    note: str = ""


@dataclass
class TraceEvent:
    """One pipeline step for later inspection."""

    step: str
    agent: str
    model: str | None
    action: str
    detail: str


@dataclass
class CaseFile:
    """Working memory for a single customer refund case."""

    message: str
    customer_id: str
    demo_today: str = field(default_factory=default_demo_today)
    intent: str | None = None
    reason_type: str | None = None
    order_id: str | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    proposed_decision: dict[str, Any] | None = None
    critique: dict[str, Any] | None = None
    decision: str | None = None
    confidence: float | None = None
    rules_applied: list[str] = field(default_factory=list)
    customer_reply: str | None = None
    limitations: list[str] = field(default_factory=list)
    trace: list[TraceEvent] = field(default_factory=list)
    model_calls: int = 0

    def add_trace(
        self,
        step: str,
        agent: str,
        action: str,
        detail: str,
        model: str | None = None,
    ) -> None:
        """Append a trace event."""
        self.trace.append(
            TraceEvent(
                step=step,
                agent=agent,
                model=model,
                action=action,
                detail=detail,
            )
        )

    def next_evidence_id(self) -> str:
        """Return the next evidence id (E1, E2, ...)."""
        return f"E{len(self.evidence) + 1}"

    def add_evidence(
        self,
        *,
        source: str,
        sql: str,
        rows: list[Any],
        note: str = "",
    ) -> EvidenceItem:
        """Store a query result and return the new item."""
        item = EvidenceItem(
            id=self.next_evidence_id(),
            source=source,
            sql=sql,
            rows=rows,
            note=note,
        )
        self.evidence.append(item)
        return item

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable snapshot of the case."""
        return asdict(self)
