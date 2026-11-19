-- Run as an administrator against a fresh disposable database and cluster only.
CREATE ROLE contexta_sub_reader LOGIN PASSWORD 'local-sub-reader-only';
CREATE SCHEMA crm;
CREATE SCHEMA ledger;
CREATE SCHEMA reporting;
CREATE SCHEMA private_data;

CREATE TABLE crm.members (
    member_key integer PRIMARY KEY,
    market text NOT NULL,
    joined_on date NOT NULL,
    member_state text NOT NULL
);
CREATE TABLE crm.enrollments (
    enrollment_key integer PRIMARY KEY,
    member_key integer NOT NULL REFERENCES crm.members(member_key),
    started_on date NOT NULL,
    ended_on date,
    state_code text NOT NULL
);
CREATE TABLE ledger.members (member_key integer PRIMARY KEY, ledger_note text);
CREATE TABLE ledger.invoice_events (
    event_key integer PRIMARY KEY,
    invoice_key integer NOT NULL,
    member_key integer NOT NULL REFERENCES crm.members(member_key),
    booked_on date NOT NULL,
    amount numeric(12,2) NOT NULL,
    currency text NOT NULL,
    event_kind text NOT NULL,
    recorded_at timestamp NOT NULL
);
CREATE TABLE private_data.secrets (id integer PRIMARY KEY, contents text);

INSERT INTO crm.members VALUES
    (1, 'North', '2025-01-02', 'LIVE'),
    (2, 'South', '2025-01-04', 'LIVE'),
    (3, 'North', '2025-01-06', 'CLOSED'),
    (4, 'South', '2025-02-01', 'LIVE');
INSERT INTO crm.enrollments VALUES
    (1, 1, '2025-01-02', NULL, 'CURRENT'),
    (2, 1, '2025-01-10', NULL, 'CURRENT'),
    (3, 2, '2025-01-04', NULL, 'CURRENT'),
    (4, 3, '2025-01-06', '2025-02-01', 'ENDED'),
    (5, 4, '2025-02-01', NULL, 'CURRENT');
-- Invoice 100 is emitted twice; only its latest event is recognized.
INSERT INTO ledger.invoice_events VALUES
    (1, 100, 1, '2025-01-10', 80, 'USD', 'POSTED', '2025-01-10 09:00:00'),
    (2, 100, 1, '2025-01-10', 80, 'USD', 'POSTED', '2025-01-10 09:01:00'),
    (3, 101, 2, '2025-01-15', 40, 'USD', 'POSTED', '2025-01-15 10:00:00'),
    (4, 102, 3, '2025-01-17', 30, 'USD', 'VOID', '2025-01-17 10:00:00'),
    (5, 103, 4, '2025-02-02', 50, 'EUR', 'POSTED', '2025-02-02 10:00:00');
INSERT INTO private_data.secrets VALUES (1, 'not for readers');

-- Vetted fixture reporting views, supplied by the data owner rather than Contexta.
CREATE VIEW reporting.member_events AS
    SELECT member_key, market, joined_on, member_state FROM crm.members;
CREATE VIEW reporting.recognized_invoices AS
    SELECT invoice_key, member_key, booked_on, amount, currency FROM (
        SELECT DISTINCT ON (invoice_key) invoice_key, member_key, booked_on, amount, currency, event_kind
        FROM ledger.invoice_events ORDER BY invoice_key, recorded_at DESC, event_key DESC
    ) latest WHERE event_kind = 'POSTED';

GRANT USAGE ON SCHEMA crm, ledger, reporting TO contexta_sub_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA crm, ledger, reporting TO contexta_sub_reader;
