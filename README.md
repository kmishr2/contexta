# Contexta

Contexta is a planned PostgreSQL onboarding and analytics chat application. The current implementation provides a liveness endpoint, a local PostgreSQL service, and development-only connection discovery.

## Requirements

Python 3.12 or newer and Docker with Compose for the optional local database.

## Install and run the API

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/health` for `{"status":"ok"}`. Neither PostgreSQL nor an LLM provider is required to start the API or run the liveness test. The app name can be set with the `CONTEXA_APP_NAME` environment variable.

## Local PostgreSQL

```sh
cp .env.example .env
docker compose config
docker compose up -d
docker compose exec postgres pg_isready -U contexta -d contexta
```

Compose uses PostgreSQL 16.6, a named data volume, and a port bound only to loopback. The example password is **only for local development**; change it for your environment. Compose reads `.env` for configuration. Initialization settings only apply to a new data volume. Stop the service with `docker compose down`; the volume persists.

## Tests

```sh
python -m pytest
```

Direct application, test, and build dependencies are pinned in `pyproject.toml` for repeatable installs. Transitive dependencies and the Docker image digest are not locked, so installs are not fully reproducible; introduce a lock file and image digest before production use.

Phase 3 will add semantic onboarding and approved business definitions.

## Phase 2: local discovery

Connection APIs are disabled by default. `CONTEXA_DEVELOPMENT_OWNER=true` gives every caller owner access: use it only on a trusted local machine, bind the API to loopback, and never expose it to a network. Operator-configured local bearer identities and per-connection analyst grants are available below; subject-area authorization and production identity are not implemented. The server stores a credential **reference** and resolves its password from an environment variable whose name begins `CONTEXA_SOURCE_`; never submit a password in the API. Destination host/port pairs are explicitly allowlisted, and the policy is rechecked on every source connection. TLS uses `verify-full` and requires `CONTEXA_SOURCE_SSLROOTCERT`, except when `CONTEXA_ALLOW_INSECURE_LOCAL_SOURCES=true` is explicitly set for a loopback host. Actual source privileges remain the database operator's responsibility.

The following uses a fresh, disposable Compose volume and the example credentials. The commerce seed creates a database role and must only be run once on an isolated cluster:

```sh
cp .env.example .env
POSTGRES_PORT=55439 docker compose up -d
POSTGRES_PORT=55439 docker compose exec postgres createdb -U contexta contexta_source_test
POSTGRES_PORT=55439 docker compose exec -T postgres psql -U contexta -d contexta_source_test -v ON_ERROR_STOP=1 < scripts/commerce.sql
export CONTEXA_METADATA_URL='postgresql+psycopg://contexta:local-development-only@127.0.0.1:55439/contexta'
export CONTEXA_DEVELOPMENT_OWNER=true
export CONTEXA_ALLOWED_DESTINATIONS='["127.0.0.1:55439"]'
export CONTEXA_ALLOW_INSECURE_LOCAL_SOURCES=true
export CONTEXA_SOURCE_COMMERCE=local-reader-only
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1
```

Register the fixture and use its returned ID to verify and discover it:

```sh
curl -X POST http://127.0.0.1:8000/connections -H 'Content-Type: application/json' -d '{"label":"Commerce","host":"127.0.0.1","port":55439,"database":"contexta_source_test","username":"contexta_reader","credential_ref":"CONTEXA_SOURCE_COMMERCE","schemas":["sales","billing"]}'
curl -X POST http://127.0.0.1:8000/connections/CONNECTION_ID/verify
curl -X POST http://127.0.0.1:8000/connections/CONNECTION_ID/discover
curl http://127.0.0.1:8000/connections/CONNECTION_ID/catalog
```

Discovery reads schema metadata, not rows. It records only relations with schema usage and table-level `SELECT` for the runtime reader; schemas without usage fail verification. Rescans add snapshots and report whether their normalized fingerprint changed. Semantic definitions and selective invalidation arrive in later phases. Snapshot contents may include database comments and should be treated as sensitive metadata.

To run PostgreSQL integration tests on that disposable setup, with the API stopped:

```sh
export CONTEXA_TEST_METADATA_URL="$CONTEXA_METADATA_URL"
export CONTEXA_TEST_SOURCE_ADMIN_URL='postgresql+psycopg://contexta:local-development-only@127.0.0.1:55439/contexta_source_test'
python -m pytest
```

The integration test changes a fixture column and grant temporarily; never point it at a real database. Without those two test URLs it is skipped. It expects the fixture and migration above, port 55439, and the example password. The metadata and source databases use separate connections and roles; use independent deployment credentials outside this disposable fixture.

## Semantic onboarding (local prototype)

Open `http://127.0.0.1:8000/` to register or select a connection, verify access, discover its catalog, save a draft, run a reference check, and publish. The screen is local-only. Select a connection and saved revision to resume work after a reload.

By default, the question box uses deterministic matching on relation names. Optionally enable the local AI integration described below to get model-generated source suggestions and a focused question. Suggestions remain unapproved and require owner review.

After discovering a connection, `POST /connections/{id}/onboarding/messages` gives deterministic, unapproved name-based suggestions. `PUT /connections/{id}/metrics/{metric_id}/draft` creates a revision; `POST .../verify` checks it against a fixed half-open date range and expected value, and `POST .../publish` publishes the latest passing revision. `GET .../revisions/{revision}` shows its definition, check, and status. The API documentation at `/docs` describes the fields.

Metrics can use row counts, distinct counts, sums, averages, and ratios of those aggregates on a single discovered table or view, with a DATE column and up to ten fixed filters combined with AND. Ratio numerator and denominator use the same source, date window, and filters; for different populations or sources, use an owner-approved reporting view. Joins, multiple fact sources, metric-specific time zones, and a full conversational UI are not yet supported. Define currencies and units explicitly: the system cannot infer whether a monetary column combines currencies. For the commerce fixture, the `billing.revenue_events` view can be summed with `event_date` and a fixed `currency` filter; January 2025 USD is 100. Product allocation is not defined. An owner must review the meaning of each definition and reference result.

A rescan marks a table-based definition stale when its discovered source object changes or becomes unreadable, while unrelated table definitions remain available. View-based definitions are conservatively marked stale on any catalog change until view dependencies can be tracked. When a rescan detects lost schema access, definitions in that schema and view definitions are marked stale even though the scan fails. Changes to dependencies outside the discovered catalog may not be detected. Stale revisions stay stale even if the source is restored; save and verify a new revision. Run a rescan after source changes. A source change made without a rescan is not automatically detected, so this prototype is not ready for production or real data.


## Local analytics chat

After publishing a metric, use the **Ask** section on the local page. The deterministic interpreter supports these forms:

```text
What was Revenue USD last month?
last month
metric revenue_usd from 2025-01-01 to 2025-02-01
metric revenue_usd
from 2025-02-01 to 2025-03-01
```

Dates are half-open: the start is included and the end excluded. The second form asks for dates; the third uses that pending metric or the previous successful metric in the same chat. Only ready, non-stale metrics for the chat's connection are queried. Results include the metric revision, dates, data status and SQL with bound values omitted. Sums with no rows return null; counts can return zero and are labeled `no_matching_rows`. A source with rows but no non-null values is labeled `missing_values`; partial nulls are labeled `partial_values`. A ratio with a zero denominator returns null and `zero_denominator` rather than zero.

“Last month” means the previous calendar month in the deployment-wide `CONTEXA_REPORTING_TIMEZONE` (an IANA time zone, default `UTC`), using the server clock. Effective dates and time zone are returned and stored with the intent. Metric names must match exactly, ignoring case; ambiguous names require an explicit ID. In deterministic mode, other relative periods are not implemented. Multi-dimension breakdowns, multiple metrics, production identity and subject-area permissions are not implemented. This remains a limited local prototype, not a general natural-language interface. An owner must have already checked currency, filters and source meaning. Analyst chats can be reopened from the connection-scoped chat selector; the most recent 50 exchanges (up to 512 KiB total) are returned, and each chat accepts up to 200 exchanges. Messages, displayed aggregate results, metric definitions and sanitized SQL are stored in the metadata database; raw source rows are not stored. Query intents and metric/snapshot versions are stored for provenance. Deleting a chat permanently deletes its messages, stored results, and associated query-run records. Existing local setups need `alembic upgrade head` before using chat. Continue to use disposable data only.


## Optional local AI for onboarding

Contexta can use Ollama running on this machine for onboarding suggestions. It sends the owner's question and at most 12 catalog objects with up to 30 column names and types each to `http://127.0.0.1:11434`; database comments, rows, and credentials are excluded. A bounded subset may omit relevant objects. The model cannot publish definitions or run SQL. Only returned sources present in that subset are accepted.

Install Ollama using its [macOS instructions](https://docs.ollama.com/macos). Start the local server with cloud features disabled in a separate terminal, then download the local Apache-2.0-licensed model (about 4.7 GB):

```sh
# Terminal 1
OLLAMA_NO_CLOUD=1 ollama serve

# Terminal 2
ollama pull qwen2.5:7b-instruct-q4_K_M
export CONTEXA_LOCAL_AI_ONBOARDING=true
export CONTEXA_LOCAL_AI_CHAT=true
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1
```

Start Ollama before the API. The model tag and loopback address are fixed in the current adapter; it does not fall back to a hosted model. If Ollama or the model is unavailable, the onboarding request returns a local-model error. Unset `CONTEXA_LOCAL_AI_ONBOARDING` to return to deterministic suggestions. Downloading the model requires network access; inference is local. With local AI enabled, the owner can request an editable metric proposal. The proposal is not saved or published until reviewed and explicitly submitted, verified, and published. Analyst questions can be interpreted using up to 30 published metric names and previous accepted intent; the AI proposes a plan that must be confirmed before execution. Confirmation is rejected if the catalog was refreshed or the approved revision changed. A single previously verified dimension can be used for a breakdown; additional query filters are not yet supported. If local AI chat is disabled, the deterministic interpreter remains available.

The AI is fallible: review the complete proposed definition and dates before saving or confirming a query. Do not use this development-owner prototype with real data.


## Verified breakdowns

A metric owner can list candidate dimension columns in a draft and independently verify each desired breakdown before publishing. In the local review screen, save the draft, enter a reference period and provenance, then provide the dimension name and all expected groups as JSON, for example:

```json
[{"dimension_value":"East","expected":"10"},{"dimension_value":"West","expected":"20"}]
```

Use `null` for a null dimension. Expected group values are strings and metric values are decimals represented as strings. The check requires every group and compares numeric results within the chosen tolerance; a partial, missing, truncated or mismatched result does not pass. Publish the revision after the overall reference check and any desired dimension checks. An overall metric can be published even if a dimension remains unverified, but that dimension cannot be queried. A later dimension check requires a new draft revision and publication.

In local AI chat, explicitly request a breakdown by the exact verified column name. Contexta previews the metric, dimension and date scope before confirmation; it validates the dimension again at execution. Grouped results are ordered by dimension and capped at 100 rows and 256 KiB, with truncation reported. One dimension on the same approved source is supported; joins, allocation, ranking, and extra query-time filters remain unavailable. The model can still misunderstand a request, so review the proposed plan. Run `alembic upgrade head` when updating an existing local metadata database.


## Subscriptions fixture and two-database test

The subscriptions fixture uses different tables, statuses, duplicate invoice events and an owner-supplied deduplicated reporting view. Add it to the same **disposable** Compose cluster used above:

```sh
POSTGRES_PORT=55439 docker compose exec postgres createdb -U contexta contexta_subscriptions_test
POSTGRES_PORT=55439 docker compose exec -T postgres psql -U contexta -d contexta_subscriptions_test -v ON_ERROR_STOP=1 < scripts/subscriptions.sql
export CONTEXA_SOURCE_SUB_FIXTURE=local-sub-reader-only
export CONTEXA_TEST_SUBSCRIPTIONS_ADMIN_URL='postgresql+psycopg://contexta:local-development-only@127.0.0.1:55439/contexta_subscriptions_test'
python -m pytest tests/integration/test_two_databases.py
```

This test also requires `CONTEXA_TEST_METADATA_URL` and `CONTEXA_TEST_SOURCE_ADMIN_URL` from the earlier fixture setup. It independently checks invoice arithmetic, repeated table names, source permissions, connection-scoped chats, and duplicate-event protection. For manual onboarding, register host `127.0.0.1`, port `55439`, database `contexta_subscriptions_test`, user `contexta_sub_reader`, credential reference `CONTEXA_SOURCE_SUB_FIXTURE`, and schemas `crm`, `ledger`, `reporting`. Fixture accounts and invoices are synthetic; the reporting views are supplied by the fixture owner, not created by Contexta.

## Owner onboarding conversations

With `CONTEXA_LOCAL_AI_ONBOARDING=true`, the question box records up to 12 exchanges per conversation. Each local-model request includes previous owner messages and questions plus a bounded catalog subset, and the owner can resume a saved conversation for that connection. Creating a proposal uses that history but does not save or publish a metric. A catalog rescan makes the conversation outdated; start a new one so the model sees the current schema. Requests that exceed the bounded local-model context are rejected instead of silently dropping earlier messages.

Conversation text is stored in the app-owned metadata database. You can delete an onboarding conversation from the local screen. Automatic retention and production identity are not implemented; use disposable data and avoid sensitive text until those controls are in place.

Chat and onboarding history have explicit delete controls but no automatic retention policy. Errors that do not produce a successful chat response are not recorded as exchanges. Before deploying with real data, configure identity, authorization, audit retention and deletion policies appropriate to the deployment.


## Operator-configured local identities

Contexta can alternatively use operator-configured bearer tokens. This is a **local development mode**, not production authentication: bind the API to loopback, protect the process environment, and do not use real data. It does not provide TLS, SSO, MFA, subject-area or row-level permissions, or automated key rotation. The unrestricted `CONTEXA_DEVELOPMENT_OWNER` bypass must be unset when identities are configured; the application rejects having both modes enabled.

Generate a different high-entropy token for each person:

```sh
python scripts/generate_local_token.py
```

Give each person only their own token. Store only the printed SHA-256 digest in a protected operator environment. After an owner has registered a connection, use its UUID when granting an analyst access. For example, substitute real SHA-256 digests and UUIDs in this JSON (the placeholders are not valid credentials):

```sh
export CONTEXA_IDENTITIES='[{"id":"owner_alex","role":"owner","token_sha256":"OWNER_SHA256"},{"id":"analyst_sam","role":"analyst","token_sha256":"ANALYST_SHA256","connections":["CONNECTION_UUID"]}]'
unset CONTEXA_DEVELOPMENT_OWNER
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1
```

Use the **Access token** control in the local screen; the token is held in page memory and must be re-entered after reload. Owners can manage all connections and definitions. Analysts can list only granted connections and published metrics, ask questions, and access their own chats. Analysts cannot access onboarding, drafts, catalog details, source SQL, or fixed-filter values. Each identity's chats and onboarding conversations are private to that identity. Connection grants and identities come from process configuration; restart after changing them. Use stable IDs and never reassign an ID to another person.

Legacy chats and onboarding conversations are assigned to `development-owner` by the migration. They remain available in explicit development-owner mode, but configured identities cannot access them. A shared source credential still gives all analysts using that connection its effective database visibility; use separate, appropriately restricted connections or database-enforced policies for different row access. A role or grant change blocks future access but does not retroactively erase information already seen.


## Fixed metric filters

A metric draft can include up to ten fixed filters, combined with **AND**. Supported conditions are equality, membership in a list of up to 50 values, `IS NULL`, and `IS NOT NULL`. Filter columns must belong to the approved source. Equality and membership support text, character, integer, decimal, boolean, date, and UUID columns; values are validated and bound using the catalog column type. Owners must still review the business meaning and verify the result. Filters are part of the metric definition, not arbitrary filters supplied by an analyst at query time.

For example, a captured USD payment metric can use `status IN (captured, settled)` and `currency = USD` together. Existing metrics with the earlier single `filter_column` / `filter_value` fields remain readable and executable. Saving an edited draft from the UI creates a new revision using the new representation; old published revisions are not rewritten.


## Fixture evaluation

The benchmark onboards both synthetic fixtures through the API, checks overall values, a follow-up and a verified breakdown, and tests how the interpreter handles unavailable requests. The fake mode tests the workflow; it is not a measure of model accuracy. The optional local mode tests the installed model on the same seven cases. It reports each outcome, plan match, execution success, latency, and summary counts as JSON. Model token usage is not currently reported. This small benchmark is a regression check, not evidence of general accuracy.

Use **only a fresh disposable cluster** with the commerce and subscriptions fixtures described above. The benchmark creates and removes its own app metadata records; it refuses a metadata target other than loopback port 55439 and database `contexta_meta_test`. Create that database, migrate it, then run:

```sh
POSTGRES_PORT=55439 docker compose exec postgres createdb -U contexta contexta_meta_test
export CONTEXA_METADATA_URL='postgresql+psycopg://contexta:local-development-only@127.0.0.1:55439/contexta_meta_test'
alembic upgrade head
export CONTEXA_EVAL_METADATA_URL="$CONTEXA_METADATA_URL"
python -m scripts.evaluate --disposable --mode fake
# With Ollama running locally and cloud features disabled:
python -m scripts.evaluate --disposable --mode local
```

The `--disposable` flag is required. The benchmark uses the documented fixture usernames and passwords and never confirms an unexpected model plan. It returns a nonzero exit status when any case fails. Cleanup normally runs even on errors; an abrupt process termination may leave evaluation records in the disposable database.

Local-model chat uses a conservative metric-name grounding check and may ask for clarification when a synonym does not match. Exact verified-dimension follow-ups can reuse the previous accepted metric and dates without asking the model to infer them again. All proposed queries still require confirmation.

If a question needs clarification, Contexta retains up to four clarification exchanges in the chat so a short answer can complete the request, including after reopening the chat. It accepts a published metric name or ID, a month and year, a calendar year, `Q1 2025`-style quarters, `last week`, `last month`, `last quarter`, `last year`, or explicit start and exclusive end dates as a clarification answer. Other conditions must be restated as a complete question, and extra query-time filters are not supported. Contexta calculates calendar windows and checks the dates proposed by the model against the user's request; an invented date range triggers another question. Last week runs Monday through Sunday, and last quarter is the previous calendar quarter. Relative periods use the configured reporting time zone. Comparisons use the explicit syntax below. Run `alembic upgrade head` to add clarification storage to an existing installation.

Results include a deterministic explanation and the effective date range, reporting period, breakdown and fixed-filter count. Missing values, zero denominators, no matching rows and truncated breakdowns are called out separately. Analysts see a generic fixed-filter note; owners can inspect the approved definition. These descriptions explain the query that ran and do not replace review of the metric's business meaning.

### Comparing two periods

In local AI chat mode, use the metric ID and put the baseline first, for example `compare metric orders January 2025 with February 2025`, or `compare metric orders Q1 2024 with Q1 2025`. Calendar years and explicit windows (`from 2025-01-01 to 2025-02-01`) also work. Explicit end dates are exclusive. Review both periods and confirm before either query runs. Comparison requests with extra filters, breakdowns, relative periods or additional metrics are not supported.

Both values are read from the same read-only, repeatable database snapshot and use the same published metric revision and fixed filters. The result includes the absolute difference and percentage change, calculated as `(current - baseline) / abs(baseline) * 100`, rounded to two decimal places. If the baseline is zero, percentage change is undefined. Contexta does not calculate a change if either period has missing, partial, non-finite or no matching data; it shows the status of each period instead. Each query is recorded separately in the chat provenance. A comparison does not become the context for a later follow-up.

### Monthly trends

In local AI chat mode, use `trend metric orders 2025 by month`, or specify a half-open range such as `trend metric orders from 2025-01-01 to 2025-04-01 by month`. The start and exclusive end must both be the first of a month; a trend contains at most 12 months. Review the metric revision, dates and month count, then confirm to run it. Extra filters, breakdowns and other granularities are not supported.

Each monthly value uses the same published definition and is read in the same repeatable, read-only database snapshot. Contexta shows every month and its data status, including months with no matching rows; it does not silently replace missing aggregate values with zero. Each period has a separate query-run record. A trend does not become the context for a later follow-up. Up to 12 source queries are executed per confirmed trend, each subject to the existing statement timeout.

### Building and exporting questions

The **Build a question** control lists the selected connection's published metrics and constructs a single-value, comparison or monthly-trend question from dates you choose. It places the question in chat for review; press **Send** to submit it. Comparisons and trends still require local AI chat mode and a separate confirmation before execution. The end date or end month is excluded.

Answers, comparisons and trends have a **Download CSV** button. The file includes the metric and revision, date windows, values, data statuses and query-run IDs. Grouped answers also include the dimension, null marker and truncation flag; comparison files identify baseline and current periods and report the change. Only the information visible in the result is exported, not SQL or hidden filter values. To prevent spreadsheet formula interpretation, text fields beginning with formula-like characters are prefixed with an apostrophe. Downloads are created locally in the browser and remain on the user's device after chat deletion.

Monthly trends also show an approximate line chart when at least two values can be plotted safely. Missing or non-plottable values appear as gaps; use the table or CSV for exact values and data status. The visual scale follows the plotted minimum and maximum rather than always starting at zero.

Run the result interface checks with `node --test tests/web/results.test.cjs`. These exercise question construction, CSV safety, chart gaps and the result-rendering logic without requiring a browser.
