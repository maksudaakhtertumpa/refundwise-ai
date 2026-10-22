"""Generate RefundWise AI synthetic sample data (deterministic).

Three "systems" that a real e-commerce company keeps separately:
  shop_orders   -> orders                      (order management system)
  support_desk  -> customers, refund_history   (support / CRM tool)
  policy_kb     -> refund_policy               (policy knowledge base)
"""
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

OUT = Path(sys.argv[1])
SAMPLE = OUT / "sample"
SAMPLE.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)

# ---------------------------------------------------------------- customers
customers = [
    ("C001", "Aisyah Rahman", "aisyah.r@example.com", "2024-03-12", "gold"),
    ("C002", "Daniel Tan", "daniel.tan@example.com", "2025-01-08", "standard"),
    ("C003", "Nurul Huda", "nurul.huda@example.com", "2023-11-20", "gold"),
    ("C004", "Arjun Pillai", "arjun.p@example.com", "2025-06-30", "standard"),
    ("C005", "Mei Ling Wong", "meiling.w@example.com", "2024-09-14", "standard"),
    ("C006", "Farhan Hossain", "farhan.h@example.com", "2025-02-17", "silver"),
    ("C007", "Siti Zulaikha", "siti.z@example.com", "2024-12-01", "silver"),
    ("C008", "Kevin Lim", "kevin.lim@example.com", "2026-01-05", "standard"),
    ("C009", "Priya Nair", "priya.nair@example.com", "2023-07-22", "gold"),
    ("C010", "Hafiz Ismail", "hafiz.i@example.com", "2025-10-10", "standard"),
    ("C011", "Grace Chong", "grace.chong@example.com", "2024-05-03", "silver"),
    ("C012", "Rahim Uddin", "rahim.u@example.com", "2026-04-19", "standard"),
]

# ---------------------------------------------------------------- products
products = {
    "Clothing": [("Linen Summer Dress", 59.90), ("Denim Jacket", 79.00), ("Cotton T-Shirt Pack", 34.50)],
    "Shoes": [("Trail Running Shoes", 89.00), ("Leather Loafers", 119.00), ("Kids Sneakers", 45.00)],
    "Electronics": [("Wireless Headphones", 149.00), ("Smart Watch", 229.00), ("14in Ultrabook Laptop", 1249.00),
                    ("Bluetooth Speaker", 69.00)],
    "Home": [("Ceramic Dinner Set", 95.00), ("Air Fryer", 139.00), ("Bedsheet Set", 49.00)],
    "Personal Care": [("Hair Dryer", 75.00), ("Skincare Gift Box", 55.00)],
    "Digital": [("Photo Editing Software Licence", 39.00), ("E-book Bundle", 19.00)],
}
pay_methods = ["credit_card", "debit_card", "e_wallet", "online_banking"]

orders = []

def add_order(oid, cid, odate, category, product, price, qty=1, status="delivered",
              ddate="auto", pay=None, final_sale=False):
    od = date.fromisoformat(odate)
    if ddate == "auto":
        dd = (od + timedelta(days=rng.randint(2, 5))).isoformat()
    else:
        dd = ddate
    orders.append({
        "order_id": oid, "customer_id": cid, "order_date": odate, "delivery_date": dd or "",
        "product_name": product, "category": category, "unit_price": f"{price:.2f}",
        "quantity": qty, "order_total": f"{price * qty:.2f}",
        "payment_method": pay or rng.choice(pay_methods), "status": status,
        "final_sale": "true" if final_sale else "false",
    })

# ---- Demo scenario orders (hand-written; the story the demo tells) ----
# S1 approve: damaged shoes, delivered 15 days ago, clean history, low value
add_order("ORD-1042", "C003", "2026-10-07", "Shoes", "Trail Running Shoes", 89.00, ddate="2026-10-10")
# S2 reject: electronics change-of-mind outside 15-day window
add_order("ORD-1017", "C007", "2026-08-16", "Electronics", "Wireless Headphones", 149.00, ddate="2026-08-20")
# S3 human review: defective laptop above auto-approval limit
add_order("ORD-1055", "C011", "2026-10-12", "Electronics", "14in Ultrabook Laptop", 1249.00, ddate="2026-10-15")
# S4 human review: frequent refunder (3 refunds in last 90 days)
add_order("ORD-1031", "C005", "2026-10-02", "Clothing", "Linen Summer Dress", 59.90, ddate="2026-10-06")
# S5 approve: not received, ordered 24 days ago, still 'shipped'
add_order("ORD-1060", "C009", "2026-10-01", "Home", "Ceramic Dinner Set", 95.00, status="shipped", ddate="")
# S6 reject: duplicate request, already refunded
add_order("ORD-1048", "C002", "2026-09-20", "Home", "Air Fryer", 139.00, ddate="2026-09-24", status="refunded")
# S7 reject: digital licence already delivered (non-refundable)
add_order("ORD-1066", "C010", "2026-10-18", "Digital", "Photo Editing Software Licence", 39.00, ddate="2026-10-18")
# S8 conflict: customer says "never arrived" but carrier shows delivered -> human review
add_order("ORD-1070", "C004", "2026-10-14", "Electronics", "Bluetooth Speaker", 69.00, ddate="2026-10-17")

# ---- Background orders (realistic noise) ----
oid_num = 1001
used = {o["order_id"] for o in orders}
start = date(2026, 6, 1)
while len(orders) < 48:
    oid = f"ORD-{oid_num}"
    oid_num += 1
    if oid in used:
        continue
    cid = rng.choice(customers)[0]
    cat = rng.choice(list(products))
    prod, price = rng.choice(products[cat])
    od = start + timedelta(days=rng.randint(0, 135))
    status = "delivered"
    ddate = "auto"
    if od > date(2026, 10, 19):
        status, ddate = "shipped", ""
    add_order(oid, cid, od.isoformat(), cat, prod, price,
              qty=rng.choice([1, 1, 1, 2]), status=status, ddate=ddate,
              final_sale=(cat == "Personal Care" and rng.random() < 0.5))

orders.sort(key=lambda o: o["order_id"])

# ---------------------------------------------------------------- refund history
refunds = [
    # C005 frequent refunder: 3 approved refunds in last 90 days (relative to 2026-10-25)
    ("RF-2001", "C005", "ORD-1009", "2026-08-03", 79.00, "changed_mind", "approved"),
    ("RF-2002", "C005", "ORD-1014", "2026-09-02", 45.00, "wrong_size", "approved"),
    ("RF-2003", "C005", "ORD-1022", "2026-09-29", 34.50, "changed_mind", "approved"),
    # C002 already refunded ORD-1048 (duplicate attempt in demo)
    ("RF-2004", "C002", "ORD-1048", "2026-09-28", 139.00, "defective", "approved"),
    # Normal history
    ("RF-2005", "C001", "ORD-1003", "2026-07-11", 49.00, "damaged_in_transit", "approved"),
    ("RF-2006", "C006", "ORD-1011", "2026-07-30", 229.00, "changed_mind", "rejected"),
    ("RF-2007", "C008", "ORD-1019", "2026-08-21", 59.90, "wrong_item", "approved"),
    ("RF-2008", "C012", "ORD-1027", "2026-09-15", 75.00, "changed_mind", "rejected"),
    ("RF-2009", "C003", "ORD-1005", "2025-12-02", 34.50, "wrong_size", "approved"),
]

# make sure referenced background orders belong to the right customer
by_id = {o["order_id"]: o for o in orders}
fixed_refunds = []
for rid, cid, oid, rdate, amount, reason, decision in refunds:
    o = by_id[oid]
    o["customer_id"] = cid
    if oid != "ORD-1048":
        # keep the story consistent: delivered ~10 days before the refund request
        rd = date.fromisoformat(rdate)
        o["order_date"] = (rd - timedelta(days=14)).isoformat()
        o["delivery_date"] = (rd - timedelta(days=10)).isoformat()
        o["final_sale"] = "false"
        if o["category"] in ("Digital", "Personal Care"):
            o["category"], o["product_name"] = "Clothing", "Cotton T-Shirt Pack"
            o["unit_price"], o["quantity"], o["order_total"] = "34.50", 1, "34.50"
        o["status"] = "refunded" if decision == "approved" else "delivered"
        amount = float(o["order_total"])
    fixed_refunds.append((rid, cid, oid, rdate, amount, reason, decision))
refunds = fixed_refunds
by_id["ORD-1048"]["status"] = "refunded"

# ---------------------------------------------------------------- refund policy
policy = [
    ("R1", "ALL", "changed_mind", 30, 200, "approve",
     "Unused items may be returned for a full refund within 30 days of delivery."),
    ("R2", "Electronics", "changed_mind", 15, 200, "approve",
     "Electronics change-of-mind returns are accepted only within 15 days of delivery and must be unopened."),
    ("R3", "ALL", "defective", 30, 200, "approve",
     "Items that arrive damaged or defective are refunded in full within 30 days of delivery; a photo is requested."),
    ("R4", "ALL", "not_received", 14, 200, "approve",
     "If an order has not been delivered 14 days after the order date, the customer may choose a refund or a replacement."),
    ("R5", "ALL", "any", 0, 0, "reject",
     "Items marked final sale cannot be refunded unless they are defective."),
    ("R6", "Digital", "any", 0, 0, "reject",
     "Digital products (licences, downloads) are non-refundable once delivered, unless the product does not work."),
    ("R7", "ALL", "any", 0, 200, "human_review",
     "Any refund above 200.00 must be reviewed by a support lead before approval."),
    ("R8", "ALL", "any", 90, 0, "human_review",
     "Customers with 3 or more refunds in the last 90 days are sent to human review to check for abuse."),
    ("R9", "ALL", "any", 0, 0, "reject",
     "An order can be refunded only once. Requests for an order that was already refunded are rejected."),
    ("R10", "ALL", "any", 0, 0, "human_review",
     "When the customer's claim conflicts with order or carrier records, the case goes to human review."),
]

# ---------------------------------------------------------------- write CSVs
def write_csv(name, header, rows):
    with open(SAMPLE / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

order_cols = ["order_id", "customer_id", "order_date", "delivery_date", "product_name", "category",
              "unit_price", "quantity", "order_total", "payment_method", "status", "final_sale"]
write_csv("shop_orders__orders.csv", order_cols, [[o[c] for c in order_cols] for o in orders])
write_csv("support_desk__customers.csv",
          ["customer_id", "full_name", "email", "joined_date", "loyalty_tier"], customers)
write_csv("support_desk__refund_history.csv",
          ["refund_id", "customer_id", "order_id", "request_date", "amount", "reason", "decision"],
          [[r[0], r[1], r[2], r[3], f"{r[4]:.2f}", r[5], r[6]] for r in refunds])
write_csv("policy_kb__refund_policy.csv",
          ["rule_id", "category", "reason_type", "window_days", "auto_approve_limit", "outcome", "rule_text"],
          policy)

# ---------------------------------------------------------------- seed SQL
def q(v):
    if v == "" or v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"

lines = [
    "-- RefundWise AI: seed three separate 'systems' into the Postgres that ships with Zetaris.",
    "-- Run with:  docker exec -i zetaris-postgres-1 psql -U zetaris -d metastore -v ON_ERROR_STOP=1 < data/seed_postgres.sql",
    "-- Safe to re-run: it drops and recreates only the three RefundWise databases. It never touches",
    "-- Zetaris's own 'metastore' or 'audit' databases.",
    "",
    "DROP DATABASE IF EXISTS shop_orders;",
    "DROP DATABASE IF EXISTS support_desk;",
    "DROP DATABASE IF EXISTS policy_kb;",
    "DO $$ BEGIN",
    "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'refundwise_ro') THEN",
    "    CREATE ROLE refundwise_ro LOGIN PASSWORD 'refundwise_local_ro';",
    "  END IF;",
    "END $$;",
    "CREATE DATABASE shop_orders;",
    "CREATE DATABASE support_desk;",
    "CREATE DATABASE policy_kb;",
    "",
]

def grant_block():
    return ["GRANT USAGE ON SCHEMA public TO refundwise_ro;",
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO refundwise_ro;", ""]

# shop_orders
lines += ["\\connect shop_orders", """CREATE TABLE orders (
  order_id       VARCHAR(12) PRIMARY KEY,
  customer_id    VARCHAR(8)  NOT NULL,
  order_date     DATE        NOT NULL,
  delivery_date  DATE,
  product_name   VARCHAR(80) NOT NULL,
  category       VARCHAR(30) NOT NULL,
  unit_price     NUMERIC(10,2) NOT NULL,
  quantity       INTEGER     NOT NULL,
  order_total    NUMERIC(10,2) NOT NULL,
  payment_method VARCHAR(20) NOT NULL,
  status         VARCHAR(20) NOT NULL,
  final_sale     BOOLEAN     NOT NULL
);"""]
for o in orders:
    vals = [q(o["order_id"]), q(o["customer_id"]), q(o["order_date"]), q(o["delivery_date"]),
            q(o["product_name"]), q(o["category"]), o["unit_price"], str(o["quantity"]), o["order_total"],
            q(o["payment_method"]), q(o["status"]), o["final_sale"]]
    lines.append(f"INSERT INTO orders VALUES ({', '.join(vals)});")
lines += grant_block()

# support_desk
lines += ["\\connect support_desk", """CREATE TABLE customers (
  customer_id  VARCHAR(8) PRIMARY KEY,
  full_name    VARCHAR(60) NOT NULL,
  email        VARCHAR(80) NOT NULL,
  joined_date  DATE NOT NULL,
  loyalty_tier VARCHAR(12) NOT NULL
);""", """CREATE TABLE refund_history (
  refund_id    VARCHAR(10) PRIMARY KEY,
  customer_id  VARCHAR(8) NOT NULL,
  order_id     VARCHAR(12) NOT NULL,
  request_date DATE NOT NULL,
  amount       NUMERIC(10,2) NOT NULL,
  reason       VARCHAR(30) NOT NULL,
  decision     VARCHAR(15) NOT NULL
);"""]
for c in customers:
    lines.append(f"INSERT INTO customers VALUES ({', '.join(q(v) for v in c)});")
for r in refunds:
    lines.append(f"INSERT INTO refund_history VALUES ({q(r[0])}, {q(r[1])}, {q(r[2])}, {q(r[3])}, "
                 f"{r[4]:.2f}, {q(r[5])}, {q(r[6])});")
lines += grant_block()

# policy_kb
lines += ["\\connect policy_kb", """CREATE TABLE refund_policy (
  rule_id            VARCHAR(5) PRIMARY KEY,
  category           VARCHAR(30) NOT NULL,
  reason_type        VARCHAR(20) NOT NULL,
  window_days        INTEGER NOT NULL,
  auto_approve_limit NUMERIC(10,2) NOT NULL,
  outcome            VARCHAR(15) NOT NULL,
  rule_text          VARCHAR(300) NOT NULL
);"""]
for p in policy:
    lines.append(f"INSERT INTO refund_policy VALUES ({q(p[0])}, {q(p[1])}, {q(p[2])}, {p[3]}, "
                 f"{p[4]}, {q(p[5])}, {q(p[6])});")
lines += grant_block()
lines.append("\\echo 'RefundWise seed complete: shop_orders, support_desk, policy_kb'")

(OUT / "seed_postgres.sql").write_text("\n".join(lines) + "\n")
print(f"orders={len(orders)} customers={len(customers)} refunds={len(refunds)} rules={len(policy)}")
