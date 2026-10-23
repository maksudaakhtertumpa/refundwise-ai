"""Run every sample request and write case files under output_examples/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.orchestrator import run_case  # noqa: E402


def main() -> None:
    requests_path = ROOT / "input_examples" / "requests.json"
    payload = json.loads(requests_path.read_text())
    demo_today = payload.get("demo_today") or "2026-10-25"
    out_dir = ROOT / "output_examples"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for item in payload.get("requests") or []:
        case_id = item["id"]
        print(f"Running {case_id}...", flush=True)
        case = run_case(
            item["message"],
            item["customer_id"],
            demo_today=demo_today,
            request_id=case_id,
        )
        out_path = out_dir / f"{case_id}.json"
        out_path.write_text(json.dumps(case.to_dict(), indent=2, default=str))
        rows.append(
            {
                "id": case_id,
                "expected": item.get("expected"),
                "decision": case.decision,
                "confidence": case.confidence,
                "model_calls": case.model_calls,
            }
        )

    _print_table(rows)


def _print_table(rows: list[dict]) -> None:
    """Print a fixed-width summary table."""
    headers = ("id", "expected", "decision", "confidence", "model_calls")
    str_rows = []
    for row in rows:
        confidence = row["confidence"]
        conf_text = "" if confidence is None else f"{float(confidence):.2f}"
        str_rows.append(
            (
                str(row["id"]),
                str(row["expected"] or ""),
                str(row["decision"] or ""),
                conf_text,
                str(row["model_calls"]),
            )
        )
    widths = [len(header) for header in headers]
    for values in str_rows:
        for index, value in enumerate(values):
            widths[index] = max(widths[index], len(value))

    def fmt(values: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[i]) for i, value in enumerate(values))

    print()
    print(fmt(headers))
    print("  ".join("-" * width for width in widths))
    for values in str_rows:
        print(fmt(values))


if __name__ == "__main__":
    main()
