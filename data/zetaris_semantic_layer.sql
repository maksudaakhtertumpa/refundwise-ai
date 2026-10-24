-- RefundWise semantic layer in Zetaris (run after data/zetaris_register.sql).
-- Built in the Zetaris UI on 2026-10-24 and recorded here so it can be reproduced.
-- Run ONE statement at a time in the SQL Workspace.
--
-- Layer 1  Sources      shop_orders, support_desk, policy_kb   (three separate Postgres databases)
-- Layer 2  Data mart    refundwise_mart                        (Data Product > Virtual Data Mart; curated view of the 4 tables)
-- Layer 3  Semantic     lightning.metastore.refundwise.refundwise_usl  (Data Product > Unified Semantic Layer)
--
-- The agents query layer 3. If it is missing, agent/tools_zetaris.py falls back to the source tables and logs it.

-- ---------------------------------------------------------------------------
-- Layer 2: the data mart is created in the UI (Data Product > Virtual Data Mart > Create Data Mart),
-- name refundwise_mart, then drag shop_orders.orders, support_desk.customers, support_desk.refund_history
-- and policy_kb.refund_policy onto the canvas and Save. It is then queryable, for example:
--   SELECT o.order_id, h.decision FROM refundwise_mart.orders o
--   LEFT JOIN refundwise_mart.refund_history h ON h.order_id = o.order_id WHERE o.customer_id = 'C005'

-- ---------------------------------------------------------------------------
-- Layer 3: Unified Semantic Layer. In the UI: Unified Semantic Layer > Add Namespace "refundwise" >
-- Create USL "refundwise_usl" and paste the DDL below. The SQL equivalent:
CREATE NAMESPACE IF NOT EXISTS lightning.metastore.refundwise

-- Every table needs a PRIMARY KEY. Tables linked by a FOREIGN KEY may share only the key column name.
-- The customers' email is deliberately left out: the agents never need it.
COMPILE USL IF NOT EXISTS refundwise_usl DEPLOY NAMESPACE lightning.metastore.refundwise DDL
CREATE TABLE customers (
    customer_id varchar(10) NOT NULL PRIMARY KEY,
    full_name varchar(100),
    joined_date date,
    loyalty_tier varchar(20)
);
CREATE TABLE orders (
    order_id varchar(12) NOT NULL PRIMARY KEY,
    customer_id varchar(10) NOT NULL FOREIGN KEY REFERENCES customers(customer_id),
    order_date date,
    delivery_date date,
    product_name varchar(100),
    category varchar(40),
    unit_price decimal(12,2),
    quantity int,
    order_total decimal(12,2),
    payment_method varchar(30),
    status varchar(20),
    final_sale varchar(5)
);
CREATE TABLE refund_history (
    refund_id varchar(12) NOT NULL PRIMARY KEY,
    customer_id varchar(10) NOT NULL FOREIGN KEY REFERENCES customers(customer_id),
    order_id varchar(12),
    request_date date,
    amount decimal(12,2),
    reason varchar(40),
    decision varchar(20)
);
CREATE TABLE refund_policy (
    rule_id varchar(5) NOT NULL PRIMARY KEY,
    category varchar(40),
    reason_type varchar(40),
    window_days int,
    auto_approve_limit decimal(12,2),
    outcome varchar(20),
    rule_text varchar(300)
)

-- Activate each table against its source system (activation from the data mart was rejected).
ACTIVATE USL TABLE lightning.metastore.refundwise.refundwise_usl.customers AS SELECT coalesce(customer_id, '') AS customer_id, full_name, CAST(joined_date AS DATE) AS joined_date, loyalty_tier FROM support_desk.customers

ACTIVATE USL TABLE lightning.metastore.refundwise.refundwise_usl.orders AS SELECT coalesce(order_id, '') AS order_id, coalesce(customer_id, '') AS customer_id, CAST(order_date AS DATE) AS order_date, CAST(delivery_date AS DATE) AS delivery_date, product_name, category, CAST(unit_price AS DECIMAL(12,2)) AS unit_price, CAST(quantity AS INT) AS quantity, CAST(order_total AS DECIMAL(12,2)) AS order_total, payment_method, status, CAST(final_sale AS STRING) AS final_sale FROM shop_orders.orders

ACTIVATE USL TABLE lightning.metastore.refundwise.refundwise_usl.refund_history AS SELECT coalesce(refund_id, '') AS refund_id, coalesce(customer_id, '') AS customer_id, order_id, CAST(request_date AS DATE) AS request_date, CAST(amount AS DECIMAL(12,2)) AS amount, reason, decision FROM support_desk.refund_history

ACTIVATE USL TABLE lightning.metastore.refundwise.refundwise_usl.refund_policy AS SELECT coalesce(rule_id, '') AS rule_id, category, reason_type, CAST(window_days AS INT) AS window_days, CAST(auto_approve_limit AS DECIMAL(12,2)) AS auto_approve_limit, outcome, rule_text FROM policy_kb.refund_policy

-- Check: one query across all three systems through the semantic layer (C005 has 3 approved refunds -> R8).
SELECT o.order_id, c.full_name, o.order_total, h.decision FROM lightning.metastore.refundwise.refundwise_usl.orders o JOIN lightning.metastore.refundwise.refundwise_usl.customers c ON c.customer_id = o.customer_id LEFT JOIN lightning.metastore.refundwise.refundwise_usl.refund_history h ON h.order_id = o.order_id WHERE o.customer_id = 'C005'
