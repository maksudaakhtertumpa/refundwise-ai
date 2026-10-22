# Scout Intent in RefundWise AI

RefundWise implements the **Meterless Scout Intent** engine from its spec ([engines/scout-intent/AGENTS.md](https://github.com/Meterless/Meterless/tree/main/engines/scout-intent)). Scout runs **before every action**: no agent, model call or Zetaris query happens on a raw customer message. Scout decides what the customer wants, guards against injection and policy violations, routes to the right tools, and issues a signed execution contract that the Python executor verifies.

## The pipeline

`Sense → Interpret → Guard → Route → Recommend → ExecutionContract`

| Stage | Where | What it does in RefundWise |
|---|---|---|
| Sense | `lib/scoring.js` | Stage-1 deterministic scan over the full registry (trigger phrases, synonyms, n-grams, intent-id tokens). Startup self-test enforces the 16 ms budget. Stage-2 rescoring is an optional hook (`stage2` option). |
| Interpret | `lib/interpret.js` | Binds `order_id` and `reason_type` (defective, changed_mind, wrong_item, not_received), finds entity references, and applies the four clarification rules. |
| Guard | `lib/guard.js` | Five layers: injection (patterns, role drift, out-of-band tool refs, control characters), policy packs, scope (roles and surfaces), PII redaction, rate limit. |
| Route | `lib/route.js` | Capability graph (`config/capability-graph.json`) → concrete tools, local-first. |
| Recommend | `lib/route.js`, `lib/contract.js` | Picks a Nemotron profile (`config/model-profiles.json`) and signs the contract: ULID id, trace id, HMAC-SHA256 over canonical JSON, 5-minute TTL, scope, approvals. |
| Telemetry | `lib/telemetry.js` | `scout.decision`, `scout.clarification`, `contract.issued` events in `scout/telemetry/events.jsonl` (metadata only, never injection payloads). |

The RefundWise registry (`registry/refundwise.json`) is the agent's whole surface area: `refund.request`, `order.not-received`, `order.status`, `policy.question`, `order.cancel`, `account.update`, and the `GENERAL` fallback.

## How the product uses it

`agent/router.py` calls Scout (`scout/cli.js`) for every message, then `agent/scout_gate.py` verifies the contract (signature, expiry, scope, approvals) before acting:

| Scout result | What RefundWise does | Model calls |
|---|---|---|
| `refund.request`, `order.not-received` | Multi-agent refund review. Scout's bound order id and reason let the intake agent be skipped. | 5–8 |
| `order.status` | One read-only Zetaris lookup and a templated reply | 0 |
| `policy.question` | Quotes the matching rules from `policy_kb.refund_policy` | 0 |
| `order.cancel`, `account.update` | High risk: contract carries `operator-review`, so it goes to a person | 0 |
| Blocked (injection, scope, rate limit) | Refused before any model, tool or data access | 0 |
| Clarification | Scout's question goes back to the customer | 0 |

Demo cases S9–S12 in `input_examples/requests.json` show the non-refund routes.

## Verification

```bash
bash scripts/run_scout_evals.sh
```

1. **Official Meterless eval harness** (`npm run evals` in `engines/scout-intent`, with `SCOUT_IMPL=scout/index.js`): all hard floors pass. Report: `evals/reports/meterless-official-latest.md`.
2. **RefundWise regression set** (`evals/refundwise-v1.jsonl`, 35 examples with the same metrics plus parameter accuracy): all gates pass. Report: `evals/reports/refundwise-latest.md`.
3. **Feature tests** (`test/scout.test.mjs`, 8 tests): routing two requests to different tools, parameter binding, injection block, clarification, approvals, contract signature/scope/expiry, and re-planning lineage.

## Honest limitations

- Only Stage 1 (lexical) runs today. The official v1 corpus reuses the registry's own example prompts, so its perfect score mostly proves the API and guard behaviour. The RefundWise set was used once to tune triggers, so it is no longer fully held-out. On new phrasings Stage 1 gets roughly 8 in 12 right and falls back to a clarifying question on the rest, which is the spec's intended safe behaviour. A Stage-2 embedding rescorer would close that gap.
- The signing key is per process (or `SCOUT_SIGNING_SECRET`). HMAC is an integrity check between Scout and the executor, not a substitute for authentication.
- `override_frequency` cannot be measured offline; it needs production telemetry.
