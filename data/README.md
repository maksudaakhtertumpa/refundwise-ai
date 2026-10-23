# RefundWise AI sample data

All data here is **synthetic**: invented customers, orders and policy rules for the Open Agent Hackathon 2026 demo. No real personal or company data is used.

## Three separate source systems

A real e-commerce company keeps this information in different tools. To mirror that, the data is loaded into three separate Postgres databases and registered in Zetaris as three separate datasources, which the agent joins with one SQL query.

| Zetaris datasource | Table | Rows | Stands in for |
|---|---|---|---|
| `shop_orders` | `orders` | 48 | Order management system |
| `support_desk` | `customers` | 12 | Support desk / CRM |
| `support_desk` | `refund_history` | 9 | Past refund requests and decisions |
| `policy_kb` | `refund_policy` | 10 | Refund policy rules (R1 to R10) |

The same data is also in `sample/` as CSV files. With `SAMPLE_MODE=true` in `.env`, `agent/tools_zetaris.py` runs the same read-only SQL against this CSV snapshot (SQLite) instead of Zetaris, so the data layer works without Docker. Model calls still go through Meterless Nightshift.

## Demo date

Scenarios are written relative to **2026-10-25** (`demo_today` in `input_examples/requests.json`), so the results stay the same whenever the demo runs.

## Demo scenarios

`input_examples/requests.json` holds 12 customer messages with the expected outcome and the reason. S1–S8 go to the multi-agent refund review: 2 approve, 3 reject and 3 human review (high value, frequent refunder, conflicting records). S9–S12 show Scout Intent routing: a blocked prompt injection, an order-status lookup, a policy question and a clarification request.

## How to load it

1. Start Zetaris (`cd ~/zetaris/zetaris-platform && docker compose start`).
2. From the project folder: `bash scripts/load_data.sh`. This creates the three databases inside the Postgres that ships with Zetaris, plus a read-only login `refundwise_ro`. It never changes Zetaris's own `metastore` or `audit` databases, and it is safe to re-run.
3. In the Zetaris SQL Workspace, run the statements in `data/zetaris_register.sql` one at a time.

## How to regenerate

The files are produced by a deterministic generator (seed 42). Edit the hand-written scenario rows in `scripts/gen_data.py` and run `python3 scripts/gen_data.py data` to rebuild the CSVs and `seed_postgres.sql`.
