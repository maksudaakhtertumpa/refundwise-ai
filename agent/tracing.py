"""JSONL trace logs: one file per case in logs/<trace_id>.jsonl, echoed to stdout.

Every event comes from the real run (CaseFile.trace). Each line records who acted,
what they did, which model answered (as reported by Nightshift), and who acts next,
so the hand-offs between agents can be followed line by line.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agent.state import CaseFile, utc_now

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path(os.getenv("REFUNDWISE_LOG_DIR") or ROOT / "logs")

# Actions that mean something was refused or went wrong, so judges can grep for them.
_STATUS = {
    "refused_sql": "refused",
    "contract.refused": "refused",
    "unavailable": "error",
    "model_error": "error",
    "budget": "error",
    "revision_cap": "escalated",
    "guard_fallback": "fallback",
    "reporter_fallback": "fallback",
    "skipped": "skipped",
    "revise": "needs_revision",
    "repair": "repaired",
}


# Agents whose repeated actions are revisions of earlier work (counted as retry_count).
_REVISABLE = {"decide", "critic", "policy-verifier", "reporter", "final-reviewer"}


def _events(case: CaseFile) -> list[dict]:
    trace = case.trace
    rows = []
    seen: dict[tuple[str, str], int] = {}
    for i, ev in enumerate(trace):
        key = (ev.agent, ev.action)
        retry = seen.get(key, 0) if ev.agent in _REVISABLE else 0
        seen[key] = seen.get(key, 0) + 1
        status = _STATUS.get(ev.action, "ok")
        if ev.action == "decide" and '"risk": "block"' in (ev.detail or ""):
            status = "blocked"
        elif ev.action == "verdict" and '"verdict": "revise"' in (ev.detail or ""):
            status = "needs_revision"
        elif ev.agent in {"policy-verifier", "final-reviewer"} and ev.action != "repair" and not str(ev.detail or "").startswith(("All ", "Every ", "Revised ")):
            status = "issues_found"
        nxt = next((t.agent for t in trace[i + 1:] if t.agent != ev.agent), None)
        rows.append(
            {
                "timestamp": ev.timestamp,
                "trace_id": case.trace_id,
                "request_id": case.request_id,
                "seq": i + 1,
                "step": ev.step,
                "agent_name": ev.agent,
                "action": ev.action,
                "model": ev.model,
                "status": status,
                "confidence": getattr(ev, "confidence", None),
                "retry_count": retry,
                "target_agent": nxt,
                "detail": (ev.detail or "")[:500],
            }
        )
    rows.append(
        {
            "timestamp": utc_now(),
            "trace_id": case.trace_id,
            "request_id": case.request_id,
            "seq": len(trace) + 1,
            "step": "result",
            "agent_name": "orchestrator",
            "action": "final",
            "model": None,
            "status": "success",
            "confidence": case.confidence,
            "retry_count": 0,
            "target_agent": "user",
            "detail": json.dumps(
                {
                    "decision": case.decision,
                    "confidence": case.confidence,
                    "rules_applied": case.rules_applied,
                    "model_calls": case.model_calls,
                    "evidence": [e.id for e in case.evidence],
                }
            ),
        }
    )
    return rows


def write_log(case: CaseFile) -> str | None:
    """Write the case trace as JSONL and echo each line to stdout. Returns the path."""
    rows = _events(case)
    echo = (os.getenv("TRACE_STDOUT") or "true").strip().lower() not in {"0", "false", "no"}
    if echo:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False), file=sys.stdout, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{case.trace_id}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:  # never fail a case because the log could not be written
        print(f"[tracing] could not write log: {exc}", file=sys.stderr)
        return None
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
