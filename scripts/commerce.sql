-- Run as an administrator against a disposable source database only.
CREATE ROLE contexta_reader LOGIN PASSWORD 'local-reader-only';
CREATE SCHEMA sales;
CREATE SCHEMA billing;
CREATE SCHEMA private_data;
CREATE TABLE sales.orders (id integer PRIMARY KEY, customer_id integer NOT NULL, created_at date NOT NULL);
CREATE TABLE sales.items (id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES sales.orders(id), sku text NOT NULL);
CREATE TABLE billing.payment_attempts (id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES sales.orders(id), amount numeric(12,2) NOT NULL, currency text NOT NULL, status text NOT NULL, captured_at date);
CREATE TABLE billing.refunds (id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES sales.orders(id), amount numeric(12,2) NOT NULL, currency text NOT NULL, refunded_at date NOT NULL);
CREATE TABLE billing.orders (id integer PRIMARY KEY, note text);
CREATE TABLE sales."Quoted Items" ("Item ID" integer PRIMARY KEY);
CREATE TABLE private_data.secret (id integer PRIMARY KEY);
INSERT INTO sales.orders VALUES (1, 101, '2025-01-10'), (2, 102, '2025-01-11');
INSERT INTO sales.items VALUES (1, 1, 'A'), (2, 1, 'B');
INSERT INTO billing.payment_attempts VALUES (1, 1, 100, 'USD', 'failed', NULL), (2, 1, 100, 'USD', 'captured', '2025-01-10'), (3, 2, 50, 'EUR', 'captured', '2025-01-11');
INSERT INTO billing.refunds VALUES (1, 1, 20, 'USD', '2025-02-03');
CREATE VIEW billing.revenue_events AS SELECT amount, currency, captured_at AS event_date FROM billing.payment_attempts WHERE status = 'captured' UNION ALL SELECT -amount, currency, refunded_at FROM billing.refunds;
GRANT USAGE ON SCHEMA sales, billing TO contexta_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA sales, billing TO contexta_reader;
