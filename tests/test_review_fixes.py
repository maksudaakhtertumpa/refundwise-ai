"""Regression tests for the external review of commit 50f000a. No model or services needed."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SAMPLE_MODE"] = "true"
os.environ["TRACE_STDOUT"] = "false"
os.environ.setdefault("REFUNDWISE_LOG_DIR", tempfile.mkdtemp(prefix="refundwise-logs-"))

from agent import runtime  # noqa: E402
from agent.checks import run_checks  # noqa: E402
from agent.evidence import enforce_customer_rows, scope_error_for  # noqa: E402
from agent.orchestrator import _fallback_reply, run_case  # noqa: E402
from agent.state import CaseFile  # noqa: E402
from agent.verifier import review_report, verify_proposal  # noqa: E402

U = "lightning.metastore.refundwise.refundwise_usl"


class CustomerIsolation(unittest.TestCase):
    def test_or_union_and_subqueries_are_refused(self):
        for sql in (f"SELECT * FROM {U}.orders WHERE customer_id = 'C003' OR 1=1",
                    f"SELECT * FROM {U}.orders WHERE customer_id = 'C003' UNION SELECT * FROM {U}.orders",
                    f"SELECT * FROM {U}.refund_history WHERE customer_id = 'C003' AND order_id IN (SELECT order_id FROM {U}.orders)"):
            self.assertIsNotNone(scope_error_for(sql, "C003"), sql)
        self.assertIsNone(scope_error_for(f"SELECT * FROM {U}.orders WHERE customer_id = 'C003' AND note = 'or this'", "C003"))

    def test_rows_of_other_customers_are_removed(self):
        rows = [{"customer_id": "C003", "order_id": "A"}, {"customer_id": "C005", "order_id": "B"}, {"order_id": "C"}]
        kept, removed = enforce_customer_rows(rows, f"{U}.orders", "C003")
        self.assertEqual([r["order_id"] for r in kept], ["A"])
        self.assertEqual(removed, 2)


def _not_received_case(order_date: str | None, delivered: bool = False) -> CaseFile:
    case = CaseFile(message="never arrived", customer_id="C009", demo_today="2026-10-25")
    case.order_id, case.reason_type = "ORD-1060", "not_received"
    case.add_evidence(source=f"{U}.orders", sql="", rows=[{
        "order_id": "ORD-1060", "customer_id": "C009", "order_date": order_date,
        "delivery_date": "2026-10-20" if delivered else None, "category": "Home", "order_total": "95.00",
        "status": "delivered" if delivered else "shipped", "final_sale": "false"}])
    case.add_evidence(source=f"{U}.refund_history", sql="", rows=[])
    run_checks(case)
    case.proposed_decision = {"decision": "approve", "rules_applied": ["R4"], "evidence_ids": ["E1"], "rationale": "Not delivered."}
    return case


class R4MinimumAge(unittest.TestCase):
    def test_three_day_old_order_cannot_be_approved(self):
        issues = " ".join(verify_proposal(_not_received_case("2026-10-22")))
        self.assertIn("R4 requires 14 days", issues)

    def test_missing_order_date_is_flagged(self):
        self.assertTrue(any("order date" in i for i in verify_proposal(_not_received_case(None))))

    def test_old_enough_order_passes(self):
        self.assertEqual(verify_proposal(_not_received_case("2026-10-01")), [])

    def test_gate_blocks_approval_even_if_every_model_accepts(self):
        msg = "My dinner set (ORD-1060) still hasn't arrived and it's been more than three weeks."
        bad = {"decision": "approve", "rules_applied": ["R4"], "confidence": 0.9,
               "rationale": "Shipped, never delivered (E1).", "evidence_ids": ["E1"]}

        def chat(messages, lane="fast", tools=None, temperature=0.2, timeout=None):
            system = messages[0]["content"]
            if "proposing a refund decision" in system:
                body = bad
            elif "strict critic" in system:
                body = {"verdict": "accept", "reason": "ok", "issues": []}
            elif "customer_reply" in system:
                body = {"customer_reply": "Your request is approved for processing.",
                        "explanation": [{"step": "Order", "evidence_id": "E1", "detail": "not delivered"}]}
            else:
                body = {}
            return {"message": {"role": "assistant", "content": json.dumps(body)}, "model": "scripted", "note": None}

        with mock.patch.object(runtime, "chat", chat):
            case = run_case(msg, "C009", demo_today="2026-10-03")  # only 2 days after the 2026-10-01 order
        self.assertEqual(case.decision, "human_review")


class PolicyCompleteness(unittest.TestCase):
    def test_all_category_rules_are_added_when_missing(self):
        from agent.evidence import _complete_policy, _POLICY_TABLE
        case = CaseFile(message="x", customer_id="C011")
        case.add_evidence(source=_POLICY_TABLE, sql="", rows=[{"rule_id": "R2", "category": "Electronics"}])
        _complete_policy(case)
        ids = {r["rule_id"] for item in case.evidence for r in item.rows}
        self.assertTrue({"R1", "R3", "R7", "R10"} <= ids)


class FinalReviewer(unittest.TestCase):
    def _case(self, decision: str) -> CaseFile:
        case = CaseFile(message="x", customer_id="C003", demo_today="2026-10-25")
        case.add_evidence(source=f"{U}.orders", sql="", rows=[{"order_id": "ORD-1042", "customer_id": "C003", "order_total": "89.00"}])
        run_checks(case)
        case.decision = decision
        return case

    def test_invented_amount_is_caught(self):
        payload = {"customer_reply": "Sorry about that.", "explanation": [{"step": "Order", "evidence_id": "E1", "detail": "Total $9999"}]}
        self.assertTrue(any("9999" in i for i in review_report(self._case("approve"), payload)))
        ok = {"customer_reply": "Sorry about that.", "explanation": [{"step": "Order", "evidence_id": "E1", "detail": "Total $89.00"}]}
        self.assertEqual(review_report(self._case("approve"), ok), [])

    def test_refund_promise_on_reject_is_caught(self):
        payload = {"customer_reply": "We will refund you in full.", "explanation": [{"step": "Order", "evidence_id": "E1"}]}
        self.assertTrue(any(i.startswith("Reply:") for i in review_report(self._case("reject"), payload)))
        fine = {"customer_reply": "We are unable to refund this order.", "explanation": [{"step": "Order", "evidence_id": "E1"}]}
        self.assertEqual(review_report(self._case("reject"), fine), [])
        quote = {"customer_reply": "Unused items may be returned for a full refund within 30 days; your order arrived 31 days ago.",
                 "explanation": [{"step": "Order", "evidence_id": "E1"}]}
        self.assertEqual(review_report(self._case("reject"), quote), [], "quoting the policy is not a promise")

    def test_payment_promises_are_caught_and_fallback_makes_none(self):
        payload = {"customer_reply": "Approved! It will be credited within 5-7 business days.", "explanation": [{"step": "Order", "evidence_id": "E1"}]}
        self.assertTrue(any("payment" in i for i in review_report(self._case("approve"), payload)))
        self.assertNotIn("business days", _fallback_reply("approve"))


class IsolationUnderEveryTableName(unittest.TestCase):
    """Review of ec0e385: source and data-mart names bypassed the scope check and row filter."""

    NAMES = ("shop_orders.orders", "refundwise_mart.orders", '"shop_orders"."orders"', "shop_orders . orders",
             "orders", f"{U}.orders", "support_desk.refund_history", "refundwise_mart.refund_history")

    def test_every_name_needs_this_customers_filter(self):
        for name in self.NAMES:
            self.assertIsNotNone(scope_error_for(f"SELECT * FROM {name}", "C003"), name)
            self.assertIsNotNone(scope_error_for(f"SELECT * FROM {name} WHERE customer_id <> 'C003'", "C003"), name)
            self.assertIsNone(scope_error_for(f"SELECT * FROM {name} WHERE customer_id = 'C003'", "C003"), name)

    def test_customers_table_is_refused_under_every_name(self):
        for name in ("support_desk.customers", "refundwise_mart.customers", '"support_desk"."customers"', f"{U}.customers"):
            self.assertIsNotNone(scope_error_for(f"SELECT * FROM {name} WHERE customer_id = 'C003'", "C003"), name)

    def test_sample_mode_rows_are_filtered_whatever_the_name(self):
        from agent.evidence import infer_source
        from agent.tools_zetaris import run_sql
        for sql in ("SELECT * FROM shop_orders.orders", "SELECT * FROM refundwise_mart.orders"):
            payload = run_sql(sql)
            self.assertTrue(payload["ok"], payload.get("error"))
            self.assertGreater(len({r["customer_id"] for r in payload["rows"]}), 1, "the attack really reads other customers")
            self.assertEqual(infer_source(sql), f"{U}.orders")
            kept, _ = enforce_customer_rows(payload["rows"], infer_source(sql), "C003", sql)
            self.assertTrue(kept and all(r["customer_id"] == "C003" for r in kept), sql)

    def test_model_written_alias_queries_never_leak_rows(self):
        attacks = ["SELECT * FROM shop_orders.orders", "SELECT * FROM refundwise_mart.orders",
                   'SELECT * FROM "support_desk"."refund_history"',
                   "SELECT order_id, order_total FROM shop_orders.orders WHERE customer_id = 'C003'"]
        sent = {"done": False}

        def chat(messages, lane="fast", tools=None, temperature=0.2, timeout=None):
            if tools:
                if sent["done"]:
                    return {"message": {"role": "assistant", "content": "done"}, "model": "scripted", "note": None}
                sent["done"] = True
                calls = [{"id": f"t{i}", "type": "function",
                          "function": {"name": "run_sql", "arguments": json.dumps({"sql": sql})}}
                         for i, sql in enumerate(attacks)]
                return {"message": {"role": "assistant", "content": "", "tool_calls": calls}, "model": "scripted", "note": None}
            return {"message": {"role": "assistant", "content": "{}"}, "model": "scripted", "note": None}

        with mock.patch.object(runtime, "chat", chat):
            case = run_case("My hair dryer from ORD-1020 stopped heating. I want a refund.", "C003", demo_today="2026-10-25")
        leaked = [r for item in case.evidence for r in item.rows
                  if isinstance(r, dict) and "customer_id" in r and r["customer_id"] != "C003"]
        self.assertEqual(leaked, [])
        self.assertGreaterEqual(sum(1 for e in case.trace if e.action == "refused_sql"), 3)


class RepairNeverKeepsAWrongAmount(unittest.TestCase):
    """Review of ec0e385: a flagged $9999 in the reply survived _repair()."""

    def test_reply_with_invented_amount_is_replaced_and_rechecked(self):
        from agent import reporter
        case = FinalReviewer()._case("approve")
        bad = {"customer_reply": "Your refund of $9999 is approved for processing.",
               "explanation": [{"step": "Order total", "evidence_id": "E1", "detail": "Order total $89.00"}]}

        def chat(messages, lane="fast", tools=None, temperature=0.2, timeout=None):
            return {"message": {"role": "assistant", "content": json.dumps(bad)}, "model": "scripted", "note": None}

        with mock.patch.object(runtime, "chat", chat):
            reporter.write_report(case)
        self.assertNotIn("9999", case.customer_reply)
        self.assertNotIn("9999", json.dumps(case.explanation))
        self.assertEqual(review_report(case, {"customer_reply": case.customer_reply, "explanation": case.explanation}), [])
        self.assertTrue(any("Reply: mentions $9999" in e.detail for e in case.trace if e.action == "review"))


if __name__ == "__main__":
    unittest.main()
