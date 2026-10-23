"""Entry point, trace logs and anti-hardcoding checks. No model, Zetaris or Nightshift needed.

These cases are decided before any model call (Scout block, order status), and
SAMPLE_MODE serves the CSV snapshot, so they run anywhere with Python and Node 18+.
Run:  .venv/bin/python -m unittest discover tests -v
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SAMPLE_MODE"] = "true"
os.environ["TRACE_STDOUT"] = "false"
_LOGS = tempfile.mkdtemp(prefix="refundwise-logs-")
os.environ["REFUNDWISE_LOG_DIR"] = _LOGS

import run  # noqa: E402


class EntryPoint(unittest.TestCase):
    def test_injection_is_refused_with_no_model_or_data(self):
        res = run.handle_request(json.loads((ROOT / "input_examples" / "example_3.json").read_text()))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"]["decision"], "refused")
        self.assertEqual(res["model_calls"], 0)
        self.assertEqual(res["evidence"], [])
        self.assertEqual(res["request_id"], "example-003")

    def test_different_inputs_give_different_outputs(self):
        status = run.handle_request({"customer_id": "C003", "user_query": "Hey, where's ORD-1042 right now? Has it shipped?"})
        policy = run.handle_request({"customer_id": "C001", "user_query": "How long do I have to send electronics back?"})
        self.assertEqual(status["route"], "order.status")
        self.assertEqual(policy["route"], "policy.question")
        self.assertIn("ORD-1042", status["result"]["customer_reply"])
        self.assertIn("R2", policy["result"]["rules_applied"])
        self.assertNotEqual(status["result"]["customer_reply"], policy["result"]["customer_reply"])
        self.assertEqual(status["evidence"][0]["source"], "shop_orders.orders")

    def test_bad_request_is_a_structured_error(self):
        with self.assertRaises(run.BadRequest):
            run.handle_request({"customer_id": "C003"})


class TraceLogs(unittest.TestCase):
    def test_log_written_with_agents_models_and_handoffs(self):
        res = run.handle_request({"request_id": "t-log", "customer_id": "C003", "user_query": "Hey, where's ORD-1042 right now? Has it shipped?"})
        path = Path(res["log_path"])
        path = path if path.is_absolute() else ROOT / path
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertGreaterEqual(len({r["agent_name"] for r in rows}), 3)
        for key in ("timestamp", "trace_id", "agent_name", "action", "model", "status", "target_agent"):
            self.assertIn(key, rows[0])
        self.assertTrue(all(r["trace_id"] == res["trace_id"] and r["request_id"] == "t-log" for r in rows))
        self.assertEqual(rows[-1]["action"], "final")


class AntiHardcoding(unittest.TestCase):
    RUNTIME = ["app.py", "run.py", *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "agent").glob("*.py"))]

    def test_runtime_code_never_reads_output_examples(self):
        for rel in self.RUNTIME:
            self.assertNotIn("output_examples", (ROOT / rel).read_text(), rel)

    def test_no_secrets_in_tracked_files(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        if not files:
            self.skipTest("not a git checkout")
        self.assertNotIn(".env", files)
        pattern = re.compile(r"nvapi-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|eyJ[A-Za-z0-9_-]{30,}\.eyJ")
        for rel in files:
            p = ROOT / rel
            if p.suffix in {".png", ".jpg", ".zip"} or not p.is_file():
                continue
            self.assertIsNone(pattern.search(p.read_text(errors="ignore")), rel)


if __name__ == "__main__":
    unittest.main()
