"""RefundWise AI entry point: run one request without the UI.

  python run.py --input input_examples/example_1.json
  python run.py --customer C003 --message "My shoes from ORD-1042 arrived broken"
  python run.py --serve --port 8000        # POST /run with the same JSON body

Request:  {"request_id": "...", "customer_id": "C003", "user_query": "..."}
Response: decision, confidence, rules, reply, cited explanation, evidence (SQL),
          the critic feedback loop, models used, and the path of the JSONL trace log.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.orchestrator import run_case  # noqa: E402
from agent.state import default_demo_today  # noqa: E402


class BadRequest(ValueError):
    pass


def build_response(case) -> dict:
    """Turn a finished CaseFile into the JSON response contract."""
    agents = list(dict.fromkeys(t.agent for t in case.trace if t.action != "skipped"))
    revisions = sum(1 for t in case.trace if t.agent == "orchestrator" and t.action == "revise")
    critique = case.critique or {}
    return {
        "request_id": case.request_id,
        "trace_id": case.trace_id,
        "status": "success",
        "route": (case.scout or {}).get("intent"),
        "agents_used": agents,
        "result": {
            "decision": case.decision,
            "confidence": case.confidence,
            "rules_applied": case.rules_applied,
            "customer_reply": case.customer_reply,
            "explanation": case.explanation,
            "limitations": case.limitations,
        },
        "evidence": [
            {"id": e.id, "source": e.source, "sql": e.sql, "row_count": len(e.rows)} for e in case.evidence
        ],
        "collaboration": {
            "feedback_loop_completed": bool(critique),
            "critic_verdict": critique.get("verdict"),
            "critic_reason": critique.get("reason"),
            "revision_count": revisions,
        },
        "scout": case.scout,
        "model_calls": case.model_calls,
        "models_used": dict(Counter(t.model for t in case.trace if t.model)),
        "log_path": case.log_path,
    }


def handle_request(body: dict) -> dict:
    """Validate a request body, run the agents, and return the response contract."""
    if not isinstance(body, dict):
        raise BadRequest("Body must be a JSON object.")
    query = body.get("user_query") or body.get("message")
    customer = body.get("customer_id")
    if not isinstance(query, str) or not query.strip():
        raise BadRequest("'user_query' (the customer message) is required.")
    if not isinstance(customer, str) or not customer.strip():
        raise BadRequest("'customer_id' is required, for example 'C003'.")
    case = run_case(
        query.strip(),
        customer.strip(),
        demo_today=body.get("demo_today") or default_demo_today(),
        request_id=body.get("request_id"),
    )
    return build_response(case)


def _error(status: str, message: str, request_id=None) -> dict:
    return {"request_id": request_id, "status": status, "error": message}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, _error("not_found", "Use POST /run or GET /health."))

    def do_POST(self):  # noqa: N802
        if self.path != "/run":
            self._send(404, _error("not_found", "Use POST /run."))
            return
        body = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, handle_request(body))
        except (json.JSONDecodeError, BadRequest) as exc:
            self._send(400, _error("bad_request", str(exc), (body or {}).get("request_id") if isinstance(body, dict) else None))
        except Exception as exc:  # structured error instead of a stack trace
            self._send(500, _error("error", f"{type(exc).__name__}: {exc}"))


def main() -> int:
    p = argparse.ArgumentParser(description="Run RefundWise AI on one request.")
    p.add_argument("--input", help="JSON file with request_id, customer_id and user_query")
    p.add_argument("--customer", help="customer id, for example C003")
    p.add_argument("--message", help="the customer message")
    p.add_argument("--out", help="also write the response JSON to this file")
    p.add_argument("--serve", action="store_true", help="start an HTTP server with POST /run")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    if args.serve:
        server = ThreadingHTTPServer((args.host, args.port), _Handler)
        print(f"RefundWise listening on http://{args.host}:{args.port}  (POST /run, GET /health)", file=sys.stderr)
        server.serve_forever()
        return 0

    if args.input:
        body = json.loads(Path(args.input).read_text())
    elif args.customer and args.message:
        body = {"customer_id": args.customer, "user_query": args.message}
    else:
        p.error("give --input FILE, or --customer and --message, or --serve")
    try:
        response = handle_request(body)
    except BadRequest as exc:
        response = _error("bad_request", str(exc), body.get("request_id") if isinstance(body, dict) else None)
    text = json.dumps(response, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if response.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
