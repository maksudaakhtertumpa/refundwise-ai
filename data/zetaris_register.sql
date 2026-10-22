-- Register RefundWise's three source systems in Zetaris.
-- Paste into the Zetaris SQL Workspace (http://localhost:3000) and run ONE statement at a time.
-- 'postgres' is the database's hostname inside the Zetaris Docker network.
-- refundwise_ro is a read-only login created by data/seed_postgres.sql (local demo data only).

-- 1. Order management system
CREATE DATASOURCE shop_orders DESCRIBE BY 'Order management system' OPTIONS (jdbcdriver 'org.postgresql.Driver', jdbcurl 'jdbc:postgresql://postgres:5432/shop_orders', username 'refundwise_ro', password 'refundwise_local_ro', fetchsize '1000')

-- 2. Support desk / CRM
CREATE DATASOURCE support_desk DESCRIBE BY 'Support desk and customer history' OPTIONS (jdbcdriver 'org.postgresql.Driver', jdbcurl 'jdbc:postgresql://postgres:5432/support_desk', username 'refundwise_ro', password 'refundwise_local_ro', fetchsize '1000')

-- 3. Refund policy knowledge base
CREATE DATASOURCE policy_kb DESCRIBE BY 'Refund policy knowledge base' OPTIONS (jdbcdriver 'org.postgresql.Driver', jdbcurl 'jdbc:postgresql://postgres:5432/policy_kb', username 'refundwise_ro', password 'refundwise_local_ro', fetchsize '1000')

-- 4. Import the tables
REGISTER DATASOURCE TABLES FROM shop_orders

REGISTER DATASOURCE TABLES FROM support_desk

REGISTER DATASOURCE TABLES FROM policy_kb

-- 5. Check: one query that joins all three systems (expect ORD-1042, Nurul Huda, Shoes, 89.00, 1 past refund)
SELECT o.order_id, c.full_name, o.category, o.order_total, o.delivery_date, COALESCE(h.past_refunds, 0) AS past_refunds, p.rule_text FROM shop_orders.orders o JOIN support_desk.customers c ON c.customer_id = o.customer_id LEFT JOIN (SELECT customer_id, COUNT(*) AS past_refunds FROM support_desk.refund_history GROUP BY customer_id) h ON h.customer_id = o.customer_id JOIN policy_kb.refund_policy p ON p.rule_id = 'R3' WHERE o.order_id = 'ORD-1042'
