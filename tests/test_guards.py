"""Deterministic safety and policy tests. No model, Zetaris or Nightshift needed.

Run:  .venv/bin/python -m unittest discover tests -v
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SAMPLE_MODE"] = "true"  # read the CSV snapshot instead of Zetaris

from agent import scout_gate  # noqa: E402
from agent.checks import run_checks  # noqa: E402
from agent.critic import apply_hard_guards  # noqa: E402
from agent.evidence import scope_error_for  # noqa: E402
from agent.state import CaseFile  # noqa: E402
from agent.tools_zetaris import _safety_error, run_sql  # noqa: E402


def case_with(order_rows, history_rows, customer="C003", order_id="ORD-1042", reason="defective"):
    case = CaseFile(message="test", customer_id=customer, demo_today="2026-10-25")
    case.order_id, case.reason_type = order_id, reason
    case.add_evidence(source="lightning.metastore.refundwise.refundwise_usl.orders", sql="", rows=order_rows)
    case.add_evidence(source="lightning.metastore.refundwise.refundwise_usl.refund_history", sql="", rows=history_rows)
    run_checks(case)
    return case


ORDER = {
    "order_id": "ORD-1042", "customer_id": "C003", "order_date": "2026-10-07", "delivery_date": "2026-10-10",
    "category": "Shoes", "order_total": "89.00", "status": "delivered", "final_sale": "false",
}


class SqlSafety(unittest.TestCase):
    def test_blocks_multiple_statements(self):
        self.assertIsNotNone(_safety_error("SELECT 1; DROP TABLE lightning.metastore.refundwise.refundwise_usl.orders"))

    def test_blocks_writes_and_unknown_tables(self):
        self.assertIsNotNone(_safety_error("DELETE FROM lightning.metastore.refundwise.refundwise_usl.orders"))
        self.assertIsNotNone(_safety_error("WITH x AS (SELECT 1) INSERT INTO a SELECT * FROM x"))
        self.assertIsNotNone(_safety_error("SELECT * FROM metastore.users"))

    def test_allows_normal_reads_and_keywords_inside_values(self):
        self.assertIsNone(_safety_error("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.orders WHERE order_id = 'ORD-1042'"))
        self.assertIsNone(_safety_error("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.refund_policy WHERE rule_text LIKE '%update%'"))

    def test_model_sql_must_be_customer_scoped(self):
        self.assertIsNotNone(scope_error_for("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.refund_history", "C003"))
        self.assertIsNotNone(scope_error_for("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.orders WHERE customer_id = 'C005'", "C003"))
        self.assertIsNotNone(scope_error_for("SELECT email FROM lightning.metastore.refundwise.refundwise_usl.customers", "C003"))
        self.assertIsNone(scope_error_for("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.refund_history WHERE customer_id = 'C003'", "C003"))
        self.assertIsNone(scope_error_for("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.refund_policy", "C003"))


class DataMart(unittest.TestCase):
    def test_mart_and_source_names_are_allowed_and_mapped(self):
        from agent.tools_zetaris import to_source_tables
        self.assertIsNone(_safety_error("SELECT * FROM shop_orders.orders WHERE order_id = 'ORD-1042'"))
        self.assertIsNone(_safety_error("SELECT * FROM refundwise_mart.orders WHERE order_id = 'ORD-1042'"))
        self.assertEqual(
            to_source_tables("SELECT * FROM refundwise_mart.orders o JOIN refundwise_mart.refund_history h ON 1=1"),
            "SELECT * FROM shop_orders.orders o JOIN support_desk.refund_history h ON 1=1",
        )

    def test_usl_names_map_to_sources(self):
        from agent.tools_zetaris import to_source_tables
        self.assertIsNone(_safety_error("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.orders WHERE customer_id = 'C003'"))
        self.assertEqual(to_source_tables("SELECT * FROM lightning.metastore.refundwise.refundwise_usl.refund_policy"), "SELECT * FROM policy_kb.refund_policy")
        self.assertIsNotNone(_safety_error("SELECT * FROM lightning.metastore.other.secret_table"))

    def test_sample_mode_serves_the_mart(self):
        res = run_sql("SELECT o.order_id, h.decision FROM refundwise_mart.orders o "
                      "JOIN refundwise_mart.refund_history h ON h.order_id = o.order_id WHERE o.customer_id = 'C005'")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue(any(r["decision"] == "approved" for r in res["rows"]))


class Checks(unittest.TestCase):
    def test_other_customers_refunds_are_not_counted(self):
        others = [
            {"refund_id": f"RF-{i}", "customer_id": "C005", "order_id": "X", "request_date": "2026-10-01", "decision": "approved"}
            for i in range(3)
        ]
        case = case_with([ORDER], others)
        self.assertEqual(case.checks["approved_refunds_last_90_days"], 0)
        self.assertIsNone(apply_hard_guards(case))

    def test_order_of_another_customer_goes_to_review(self):
        case = case_with([{**ORDER, "customer_id": "C999"}], [], customer="C003")
        self.assertFalse(case.checks["order_belongs_to_customer"])
        guard = apply_hard_guards(case)
        self.assertEqual(guard["decision"], "human_review")
        self.assertIn("different customer", guard["reason"])

    def test_policy_guards(self):
        self.assertEqual(apply_hard_guards(case_with([{**ORDER, "status": "refunded"}], []))["rule"], "R9")
        self.assertEqual(apply_hard_guards(case_with([{**ORDER, "order_total": "1249.00"}], []))["rule"], "R7")
        frequent = [
            {"refund_id": f"RF-{i}", "customer_id": "C003", "order_id": f"O{i}", "request_date": "2026-09-1%d" % i, "decision": "approved"}
            for i in range(3)
        ]
        self.assertEqual(apply_hard_guards(case_with([ORDER], frequent))["rule"], "R8")
        self.assertEqual(apply_hard_guards(case_with([ORDER], [], reason="not_received"))["rule"], "R10")


class SampleMode(unittest.TestCase):
    def test_reads_csv_snapshot(self):
        res = run_sql("SELECT order_id, customer_id, order_total FROM lightning.metastore.refundwise.refundwise_usl.orders WHERE order_id = 'ORD-1042'")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["rows"][0]["customer_id"], "C003")
        self.assertEqual(res.get("mode"), "sample")


class Contracts(unittest.TestCase):
    def _signed(self, **over):
        body = {
            "contractId": "01TEST",
            "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "risk": {"approvals": []},
            "scope": {"capabilities": ["order.lookup", "agent.review"]},
            **over,
        }
        sig = hmac.new(scout_gate._SECRET.encode(), scout_gate.canonical_json(body).encode(), hashlib.sha256).hexdigest()
        return {**body, "signature": sig}

    def test_executor_verification(self):
        good = self._signed()
        self.assertEqual(scout_gate.verify_contract(good, "agent.review"), (True, "ok"))
        self.assertEqual(scout_gate.verify_contract(good, "email.send")[1], "scope-mismatch")
        self.assertEqual(scout_gate.verify_contract({**good, "scope": {"capabilities": ["email.send"]}})[1], "bad-signature")
        old = self._signed(expiresAt="2020-01-01T00:00:00Z")
        self.assertEqual(scout_gate.verify_contract(old)[1], "expired")
        high = self._signed(risk={"approvals": ["operator-review"]})
        self.assertEqual(scout_gate.verify_contract(high)[1], "approval-required:operator-review")


if __name__ == "__main__":
    unittest.main()
