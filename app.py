"""Streamlit UI for the RefundWise AI explainable refund assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
REQUESTS_PATH = ROOT / "input_examples" / "requests.json"
DEMO_TODAY = "2026-10-25"
CUSTOMERS = [f"C{number:03d}" for number in range(1, 13)]
DECISION_STYLES = {
    "approve": ("#15803d", "white"),
    "reject": ("#b91c1c", "white"),
    "human_review": ("#b45309", "white"),
    "refused": ("#4b5563", "white"),
    "answered": ("#0369a1", "white"),
    "needs_info": ("#7e22ce", "white"),
}


def load_requests() -> list[dict[str, Any]]:
    """Load the twelve curated demo requests."""
    payload = json.loads(REQUESTS_PATH.read_text())
    return list(payload["requests"])


def case_dict(case: Any) -> dict[str, Any]:
    """Convert a CaseFile (or an already plain dict) to a plain dictionary."""
    if isinstance(case, dict):
        return case
    return case.to_dict()


def set_message_from_sample(requests: list[dict[str, Any]]) -> None:
    """Copy the selected sample into the message and customer controls."""
    selected = requests[st.session_state.sample_index]
    st.session_state.message_text = selected["message"]
    st.session_state.customer_id = selected["customer_id"]


def display_value(value: Any) -> str:
    """Format values for stable, human-readable Streamlit tables."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def display_rows(rows: list[Any]) -> list[dict[str, str]]:
    """Convert every table cell to a string before handing it to Streamlit."""
    converted = []
    for row in rows:
        if isinstance(row, dict):
            converted.append({str(key): display_value(value) for key, value in row.items()})
        else:
            converted.append({"Value": display_value(row)})
    return converted


def escape_markdown_dollars(value: Any) -> str:
    """Prevent dollar-delimited model text from being interpreted as LaTeX."""
    return str(value or "").replace("$", r"\$")


def render_decision(case: dict[str, Any]) -> None:
    """Render the outcome, confidence, rules, and customer-facing reply."""
    decision = case.get("decision") or "unknown"
    background, foreground = DECISION_STYLES.get(decision, ("#374151", "white"))
    confidence = case.get("confidence")
    confidence_text = "Not scored" if confidence is None else f"{float(confidence):.0%}"
    rules = ", ".join(case.get("rules_applied") or []) or "None recorded"

    st.subheader("Decision")
    st.markdown(
        f'<div style="background:{background};color:{foreground};padding:0.65rem 1rem;'
        f'border-radius:0.5rem;display:inline-block;font-size:1.35rem;font-weight:700;">'
        f"{decision.replace('_', ' ').title()}</div>",
        unsafe_allow_html=True,
    )
    critique = case.get("critique") or {}
    reasons = []
    if critique.get("reason"):
        reasons.append(str(critique["reason"]))
    hard_guard = critique.get("hard_guard") or {}
    if hard_guard.get("reason"):
        reasons.append(str(hard_guard["reason"]))
    if reasons:
        reason_text = escape_markdown_dollars(" ".join(dict.fromkeys(reasons)))
        st.markdown(f"**Why this decision:** {reason_text}")
    st.caption(f"Confidence: {confidence_text}  |  Rules applied: {rules}")
    reply = case.get("customer_reply") or "No customer reply was recorded."
    st.info(escape_markdown_dollars(reply))


def render_scout(scout: dict[str, Any]) -> None:
    """Render Scout's routing decision and safety metadata."""
    st.subheader("Scout Intent")
    risk = scout.get("risk") or {}
    if isinstance(risk, str):
        risk = {"level": risk, "flags": []}
    values = [
        {"Field": "Intent", "Value": scout.get("intent") or "—"},
        {"Field": "Score", "Value": f"{float(scout['score']):.3f}" if scout.get("score") is not None else "—"},
        {"Field": "Band", "Value": scout.get("band") or "—"},
        {"Field": "Risk level", "Value": risk.get("level") or "—"},
        {"Field": "Risk flags", "Value": ", ".join(risk.get("flags") or []) or "None"},
        {"Field": "Signed contract", "Value": scout.get("contractId") or "None"},
    ]
    st.table(display_rows(values))
    tool_plan = scout.get("toolPlan") or []
    st.caption("Tool plan")
    if tool_plan:
        st.markdown("\n".join(f"- {item}" for item in tool_plan))
    else:
        st.caption("None")


def render_evidence(evidence: list[dict[str, Any]]) -> None:
    """Render an evidence summary and expandable SQL result details."""
    st.subheader("Evidence trail")
    if not evidence:
        st.caption("No evidence was collected.")
        return
    st.table(
        display_rows(
            [
            {
                "Evidence": item.get("id", "—"),
                "Zetaris source": item.get("source", "—"),
                "Rows": len(item.get("rows") or []),
            }
            for item in evidence
            ]
        )
    )
    for item in evidence:
        label = f"{item.get('id', 'Evidence')} — {item.get('note') or item.get('source', '')}"
        with st.expander(label):
            st.code(item.get("sql") or "No SQL recorded.", language="sql")
            rows = item.get("rows") or []
            if rows:
                st.table(display_rows(rows))
            else:
                st.caption("Query returned no rows.")


def check_facts(checks: dict[str, Any]) -> list[tuple[str, str]]:
    """Turn common deterministic checks into readable, evidence-linked facts."""
    facts = []
    if checks.get("days_since_delivery") is not None:
        date = checks.get("delivery_date")
        suffix = f" ({date})" if date else ""
        facts.append(("E1", f"Delivered {checks['days_since_delivery']} days ago{suffix}"))
    if checks.get("order_total") is not None:
        amount = float(checks["order_total"])
        if checks.get("over_auto_limit"):
            facts.append(("E1 + E3", f"Order total {amount:.2f} is over the 200.00 auto-approve limit"))
        else:
            facts.append(("E1 + E3", f"Order total {amount:.2f} is under the 200.00 auto-approve limit"))
    if checks.get("approved_refunds_last_90_days") is not None:
        facts.append((
            "E2",
            f"{checks['approved_refunds_last_90_days']} approved refunds in the last 90 days",
        ))
    if checks.get("already_refunded") is not None:
        facts.append(("E2", f"Already refunded: {'yes' if checks['already_refunded'] else 'no'}"))
    if checks.get("delivered") is not None:
        facts.append(("E1", f"Delivered: {'yes' if checks['delivered'] else 'no'}"))
    if checks.get("final_sale") is not None:
        facts.append(("E1", f"Final sale: {'yes' if checks['final_sale'] else 'no'}"))
    return facts


def render_why(case: dict[str, Any]) -> None:
    """Render explanation steps and deterministic Python checks."""
    st.subheader("Why")
    explanation = case.get("explanation") or []
    checks = case.get("checks") or {}
    facts = check_facts(checks)
    fallback_needed = False
    rendered = []
    for item in explanation:
        if not isinstance(item, dict):
            rendered.append(("No evidence id", str(item)))
            continue
        evidence_id = item.get("evidence_id") or item.get("evidence_ids") or "No evidence id"
        detail = str(item.get("detail") or "").strip()
        table_names = {
            str(item.get(key) or "").strip().lower()
            for key in ("step", "source", "note")
        }
        table_names.discard("")
        if not detail or detail.lower() in table_names:
            fallback_needed = True
        else:
            rendered.append((evidence_id, detail))
    if fallback_needed or not explanation:
        rendered.extend(facts)
    if rendered:
        st.markdown(
            "\n".join(
                f"- **{evidence_id}** — {escape_markdown_dollars(detail)}"
                for evidence_id, detail in rendered
            )
        )
    else:
        st.caption("No explanation steps were recorded.")
    if checks:
        st.caption("Python checks")
        st.table(display_rows([{"Check": key, "Value": value} for key, value in checks.items()]))


def model_label(model: Any) -> str:
    """Return a compact Nemotron model label for a trace event."""
    value = str(model or "").lower()
    if "super" in value:
        return "Super"
    if "lightning" in value:
        return "Lightning"
    return "—"


def render_timeline(case: dict[str, Any]) -> None:
    """Render the auditable agent timeline and model-call count."""
    st.subheader("Agent timeline")
    trace = case.get("trace") or []
    model_counts = {"Lightning": 0, "Super": 0}
    for event in trace:
        label = model_label(event.get("model"))
        if label in model_counts:
            model_counts[label] += 1
    st.caption(
        f"Nemotron Lightning: {model_counts['Lightning']}, "
        f"Nemotron Super: {model_counts['Super']}"
    )
    if trace:
        st.table(
            display_rows(
                [
                {
                    "Step": event.get("step", "—"),
                    "Agent": event.get("agent", "—"),
                    "Action": event.get("action", "—"),
                    "Model": model_label(event.get("model")),
                    "Detail": str(event.get("detail") or "—")[:120],
                }
                for event in trace
                ]
            )
        )
        with st.expander("Full trace"):
            st.json(trace)
    else:
        st.caption("No trace events were recorded.")
    st.caption(f"Total model calls: {case.get('model_calls', 0)}")


def render_case(case: dict[str, Any]) -> None:
    """Render every explainability panel for a completed case."""
    confidence = case.get("confidence")
    scout = case.get("scout") or {}
    decision_labels = {
        "approve": "Approve",
        "reject": "Reject",
        "human_review": "Review",
        "refused": "Refused",
        "answered": "Answered",
        "needs_info": "Needs info",
    }
    decision = case.get("decision") or "unknown"
    metrics = st.columns(4)
    metrics[0].metric("Confidence", "Not scored" if confidence is None else f"{float(confidence):.0%}")
    metrics[1].metric("Model calls", case.get("model_calls", 0))
    metrics[2].metric("Evidence items", len(case.get("evidence") or []))
    latency = scout.get("latencyMs")
    metrics[3].metric("Scout latency", "—" if latency is None else f"{float(latency):.1f} ms")
    render_decision(case)
    render_scout(scout)
    render_evidence(case.get("evidence") or [])
    render_why(case)
    render_timeline(case)
    limitations = case.get("limitations") or []
    if limitations:
        st.warning("**Limitations**\n\n" + "\n".join(f"- {item}" for item in limitations))


def main() -> None:
    """Build the RefundWise Streamlit application."""
    st.set_page_config(page_title="RefundWise AI", page_icon="💡", layout="wide")
    st.title("RefundWise AI — Explainable Refund Assistant")
    requests = load_requests()

    if "message_text" not in st.session_state:
        st.session_state.message_text = requests[0]["message"]
    if "sample_index" not in st.session_state:
        st.session_state.sample_index = 0
    if "customer_id" not in st.session_state:
        st.session_state.customer_id = requests[0]["customer_id"]
    if "case" not in st.session_state:
        st.session_state.case = None

    with st.sidebar:
        st.header("Case setup")
        customer_id = st.selectbox("Customer", CUSTOMERS, key="customer_id")
        st.selectbox(
            "Sample message",
            range(len(requests)),
            index=st.session_state.sample_index,
            format_func=lambda index: f"{requests[index]['id']}: {requests[index]['message']}",
            key="sample_index",
            on_change=set_message_from_sample,
            args=(requests,),
        )
        st.caption(
            "How it works: Scout Intent → Zetaris evidence → "
            "Nemotron agents → decision"
        )
        st.caption(
            f"Demo date: {DEMO_TODAY}. This is a fixed date for the synthetic data, "
            "so every run gives the same result. It is not today's date."
        )

    left, right = st.columns([1, 1.55], gap="large")
    with left:
        st.subheader("Review request")
        st.text_area("Customer message", key="message_text", height=220)
        if st.button("Review request", type="primary", use_container_width=True):
            from agent.orchestrator import run_case

            with st.spinner("Reviewing request with RefundWise agents (live)..."):
                st.session_state.case = case_dict(
                    run_case(
                        st.session_state.message_text,
                        customer_id,
                        demo_today=DEMO_TODAY,
                    )
                )

    with right:
        case = st.session_state.case
        if case:
            render_case(case)
        else:
            st.info("Submit a request to see the decision and evidence trail.")


if __name__ == "__main__":
    main()
