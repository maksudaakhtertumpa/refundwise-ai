-- RefundWise AI: seed three separate 'systems' into the Postgres that ships with Zetaris.
-- Run with:  docker exec -i zetaris-postgres-1 psql -U zetaris -d metastore -v ON_ERROR_STOP=1 < data/seed_postgres.sql
-- Safe to re-run: it drops and recreates only the three RefundWise databases. It never touches
-- Zetaris's own 'metastore' or 'audit' databases.

DROP DATABASE IF EXISTS shop_orders;
DROP DATABASE IF EXISTS support_desk;
DROP DATABASE IF EXISTS policy_kb;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'refundwise_ro') THEN
    CREATE ROLE refundwise_ro LOGIN PASSWORD 'refundwise_local_ro';
  END IF;
END $$;
CREATE DATABASE shop_orders;
CREATE DATABASE support_desk;
CREATE DATABASE policy_kb;

\connect shop_orders
CREATE TABLE orders (
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
);
INSERT INTO orders VALUES ('ORD-1001', 'C010', '2026-06-08', '2026-06-11', 'Ceramic Dinner Set', 'Home', 95.00, 1, 95.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1002', 'C009', '2026-07-21', '2026-07-25', 'Hair Dryer', 'Personal Care', 75.00, 2, 150.00, 'credit_card', 'delivered', true);
INSERT INTO orders VALUES ('ORD-1003', 'C001', '2026-06-27', '2026-07-01', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'debit_card', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1004', 'C006', '2026-09-06', '2026-09-10', 'Linen Summer Dress', 'Clothing', 59.90, 1, 59.90, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1005', 'C003', '2025-11-18', '2025-11-22', 'Wireless Headphones', 'Electronics', 149.00, 1, 149.00, 'credit_card', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1006', 'C009', '2026-07-20', '2026-07-22', '14in Ultrabook Laptop', 'Electronics', 1249.00, 1, 1249.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1007', 'C005', '2026-06-26', '2026-06-30', 'Linen Summer Dress', 'Clothing', 59.90, 2, 119.80, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1008', 'C011', '2026-09-03', '2026-09-06', 'Smart Watch', 'Electronics', 229.00, 1, 229.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1009', 'C005', '2026-07-20', '2026-07-24', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'online_banking', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1010', 'C007', '2026-08-23', '2026-08-26', 'Smart Watch', 'Electronics', 229.00, 1, 229.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1011', 'C006', '2026-07-16', '2026-07-20', 'Air Fryer', 'Home', 139.00, 1, 139.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1012', 'C011', '2026-09-26', '2026-09-30', 'Air Fryer', 'Home', 139.00, 1, 139.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1013', 'C004', '2026-09-18', '2026-09-22', 'E-book Bundle', 'Digital', 19.00, 2, 38.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1014', 'C005', '2026-08-19', '2026-08-23', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'debit_card', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1015', 'C011', '2026-06-17', '2026-06-22', 'Bedsheet Set', 'Home', 49.00, 2, 98.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1016', 'C009', '2026-06-30', '2026-07-04', 'Wireless Headphones', 'Electronics', 149.00, 1, 149.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1017', 'C007', '2026-08-16', '2026-08-20', 'Wireless Headphones', 'Electronics', 149.00, 1, 149.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1018', 'C005', '2026-09-25', '2026-09-29', 'Ceramic Dinner Set', 'Home', 95.00, 1, 95.00, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1019', 'C008', '2026-08-07', '2026-08-11', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'e_wallet', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1020', 'C003', '2026-08-22', '2026-08-26', 'Hair Dryer', 'Personal Care', 75.00, 2, 150.00, 'e_wallet', 'delivered', true);
INSERT INTO orders VALUES ('ORD-1021', 'C004', '2026-06-21', '2026-06-26', 'Linen Summer Dress', 'Clothing', 59.90, 1, 59.90, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1022', 'C005', '2026-09-15', '2026-09-19', 'Trail Running Shoes', 'Shoes', 89.00, 1, 89.00, 'online_banking', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1023', 'C004', '2026-08-19', '2026-08-23', 'Hair Dryer', 'Personal Care', 75.00, 2, 150.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1024', 'C009', '2026-08-03', '2026-08-05', 'Ceramic Dinner Set', 'Home', 95.00, 1, 95.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1025', 'C001', '2026-07-27', '2026-07-29', 'Hair Dryer', 'Personal Care', 75.00, 1, 75.00, 'debit_card', 'delivered', true);
INSERT INTO orders VALUES ('ORD-1026', 'C002', '2026-06-19', '2026-06-23', 'Denim Jacket', 'Clothing', 79.00, 1, 79.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1027', 'C012', '2026-09-01', '2026-09-05', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1028', 'C002', '2026-09-19', '2026-09-24', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1029', 'C008', '2026-06-26', '2026-07-01', 'Photo Editing Software Licence', 'Digital', 39.00, 1, 39.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1030', 'C002', '2026-07-19', '2026-07-22', 'Trail Running Shoes', 'Shoes', 89.00, 2, 178.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1031', 'C005', '2026-10-02', '2026-10-06', 'Linen Summer Dress', 'Clothing', 59.90, 1, 59.90, 'debit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1032', 'C003', '2026-08-03', '2026-08-08', 'Bluetooth Speaker', 'Electronics', 69.00, 1, 69.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1033', 'C001', '2026-06-24', '2026-06-27', 'Photo Editing Software Licence', 'Digital', 39.00, 1, 39.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1034', 'C008', '2026-09-11', '2026-09-14', 'Ceramic Dinner Set', 'Home', 95.00, 1, 95.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1035', 'C001', '2026-09-25', '2026-09-30', 'Air Fryer', 'Home', 139.00, 1, 139.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1036', 'C003', '2026-07-26', '2026-07-28', 'Leather Loafers', 'Shoes', 119.00, 1, 119.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1037', 'C001', '2026-10-01', '2026-10-03', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1038', 'C003', '2026-06-18', '2026-06-23', 'Cotton T-Shirt Pack', 'Clothing', 34.50, 1, 34.50, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1039', 'C010', '2026-06-11', '2026-06-16', 'Kids Sneakers', 'Shoes', 45.00, 1, 45.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1040', 'C005', '2026-08-20', '2026-08-24', 'Kids Sneakers', 'Shoes', 45.00, 1, 45.00, 'online_banking', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1041', 'C003', '2026-09-26', '2026-09-28', 'E-book Bundle', 'Digital', 19.00, 1, 19.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1042', 'C003', '2026-10-07', '2026-10-10', 'Trail Running Shoes', 'Shoes', 89.00, 1, 89.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1043', 'C008', '2026-06-19', '2026-06-22', 'Hair Dryer', 'Personal Care', 75.00, 1, 75.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1048', 'C002', '2026-09-20', '2026-09-24', 'Air Fryer', 'Home', 139.00, 1, 139.00, 'debit_card', 'refunded', false);
INSERT INTO orders VALUES ('ORD-1055', 'C011', '2026-10-12', '2026-10-15', '14in Ultrabook Laptop', 'Electronics', 1249.00, 1, 1249.00, 'e_wallet', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1060', 'C009', '2026-10-01', NULL, 'Ceramic Dinner Set', 'Home', 95.00, 1, 95.00, 'debit_card', 'shipped', false);
INSERT INTO orders VALUES ('ORD-1066', 'C010', '2026-10-18', '2026-10-18', 'Photo Editing Software Licence', 'Digital', 39.00, 1, 39.00, 'credit_card', 'delivered', false);
INSERT INTO orders VALUES ('ORD-1070', 'C004', '2026-10-14', '2026-10-17', 'Bluetooth Speaker', 'Electronics', 69.00, 1, 69.00, 'credit_card', 'delivered', false);
GRANT USAGE ON SCHEMA public TO refundwise_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO refundwise_ro;

\connect support_desk
CREATE TABLE customers (
  customer_id  VARCHAR(8) PRIMARY KEY,
  full_name    VARCHAR(60) NOT NULL,
  email        VARCHAR(80) NOT NULL,
  joined_date  DATE NOT NULL,
  loyalty_tier VARCHAR(12) NOT NULL
);
CREATE TABLE refund_history (
  refund_id    VARCHAR(10) PRIMARY KEY,
  customer_id  VARCHAR(8) NOT NULL,
  order_id     VARCHAR(12) NOT NULL,
  request_date DATE NOT NULL,
  amount       NUMERIC(10,2) NOT NULL,
  reason       VARCHAR(30) NOT NULL,
  decision     VARCHAR(15) NOT NULL
);
INSERT INTO customers VALUES ('C001', 'Aisyah Rahman', 'aisyah.r@example.com', '2024-03-12', 'gold');
INSERT INTO customers VALUES ('C002', 'Daniel Tan', 'daniel.tan@example.com', '2025-01-08', 'standard');
INSERT INTO customers VALUES ('C003', 'Nurul Huda', 'nurul.huda@example.com', '2023-11-20', 'gold');
INSERT INTO customers VALUES ('C004', 'Arjun Pillai', 'arjun.p@example.com', '2025-06-30', 'standard');
INSERT INTO customers VALUES ('C005', 'Mei Ling Wong', 'meiling.w@example.com', '2024-09-14', 'standard');
INSERT INTO customers VALUES ('C006', 'Farhan Hossain', 'farhan.h@example.com', '2025-02-17', 'silver');
INSERT INTO customers VALUES ('C007', 'Siti Zulaikha', 'siti.z@example.com', '2024-12-01', 'silver');
INSERT INTO customers VALUES ('C008', 'Kevin Lim', 'kevin.lim@example.com', '2026-01-05', 'standard');
INSERT INTO customers VALUES ('C009', 'Priya Nair', 'priya.nair@example.com', '2023-07-22', 'gold');
INSERT INTO customers VALUES ('C010', 'Hafiz Ismail', 'hafiz.i@example.com', '2025-10-10', 'standard');
INSERT INTO customers VALUES ('C011', 'Grace Chong', 'grace.chong@example.com', '2024-05-03', 'silver');
INSERT INTO customers VALUES ('C012', 'Rahim Uddin', 'rahim.u@example.com', '2026-04-19', 'standard');
INSERT INTO refund_history VALUES ('RF-2001', 'C005', 'ORD-1009', '2026-08-03', 34.50, 'changed_mind', 'approved');
INSERT INTO refund_history VALUES ('RF-2002', 'C005', 'ORD-1014', '2026-09-02', 34.50, 'wrong_size', 'approved');
INSERT INTO refund_history VALUES ('RF-2003', 'C005', 'ORD-1022', '2026-09-29', 89.00, 'changed_mind', 'approved');
INSERT INTO refund_history VALUES ('RF-2004', 'C002', 'ORD-1048', '2026-09-28', 139.00, 'defective', 'approved');
INSERT INTO refund_history VALUES ('RF-2005', 'C001', 'ORD-1003', '2026-07-11', 34.50, 'damaged_in_transit', 'approved');
INSERT INTO refund_history VALUES ('RF-2006', 'C006', 'ORD-1011', '2026-07-30', 139.00, 'changed_mind', 'rejected');
INSERT INTO refund_history VALUES ('RF-2007', 'C008', 'ORD-1019', '2026-08-21', 34.50, 'wrong_item', 'approved');
INSERT INTO refund_history VALUES ('RF-2008', 'C012', 'ORD-1027', '2026-09-15', 34.50, 'changed_mind', 'rejected');
INSERT INTO refund_history VALUES ('RF-2009', 'C003', 'ORD-1005', '2025-12-02', 149.00, 'wrong_size', 'approved');
GRANT USAGE ON SCHEMA public TO refundwise_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO refundwise_ro;

\connect policy_kb
CREATE TABLE refund_policy (
  rule_id            VARCHAR(5) PRIMARY KEY,
  category           VARCHAR(30) NOT NULL,
  reason_type        VARCHAR(20) NOT NULL,
  window_days        INTEGER NOT NULL,
  auto_approve_limit NUMERIC(10,2) NOT NULL,
  outcome            VARCHAR(15) NOT NULL,
  rule_text          VARCHAR(300) NOT NULL
);
INSERT INTO refund_policy VALUES ('R1', 'ALL', 'changed_mind', 30, 200, 'approve', 'Unused items may be returned for a full refund within 30 days of delivery.');
INSERT INTO refund_policy VALUES ('R2', 'Electronics', 'changed_mind', 15, 200, 'approve', 'Electronics change-of-mind returns are accepted only within 15 days of delivery and must be unopened.');
INSERT INTO refund_policy VALUES ('R3', 'ALL', 'defective', 30, 200, 'approve', 'Items that arrive damaged or defective are refunded in full within 30 days of delivery; a photo is requested.');
INSERT INTO refund_policy VALUES ('R4', 'ALL', 'not_received', 14, 200, 'approve', 'If an order has not been delivered 14 days after the order date, the customer may choose a refund or a replacement.');
INSERT INTO refund_policy VALUES ('R5', 'ALL', 'any', 0, 0, 'reject', 'Items marked final sale cannot be refunded unless they are defective.');
INSERT INTO refund_policy VALUES ('R6', 'Digital', 'any', 0, 0, 'reject', 'Digital products (licences, downloads) are non-refundable once delivered, unless the product does not work.');
INSERT INTO refund_policy VALUES ('R7', 'ALL', 'any', 0, 200, 'human_review', 'Any refund above 200.00 must be reviewed by a support lead before approval.');
INSERT INTO refund_policy VALUES ('R8', 'ALL', 'any', 90, 0, 'human_review', 'Customers with 3 or more refunds in the last 90 days are sent to human review to check for abuse.');
INSERT INTO refund_policy VALUES ('R9', 'ALL', 'any', 0, 0, 'reject', 'An order can be refunded only once. Requests for an order that was already refunded are rejected.');
INSERT INTO refund_policy VALUES ('R10', 'ALL', 'any', 0, 0, 'human_review', 'When the customer''s claim conflicts with order or carrier records, the case goes to human review.');
GRANT USAGE ON SCHEMA public TO refundwise_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO refundwise_ro;

\echo 'RefundWise seed complete: shop_orders, support_desk, policy_kb'
