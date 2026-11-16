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

Connection APIs are disabled by default. `CONTEXA_DEVELOPMENT_OWNER=true` gives every caller owner access: use it only on a trusted local machine, bind the API to loopback, and never expose it to a network. Real authentication, analyst grants, and subject-area authorization are not implemented. The server stores a credential **reference** and resolves its password from an environment variable whose name begins `CONTEXA_SOURCE_`; never submit a password in the API. Destination host/port pairs are explicitly allowlisted, and the policy is rechecked on every source connection. TLS uses `verify-full` and requires `CONTEXA_SOURCE_SSLROOTCERT`, except when `CONTEXA_ALLOW_INSECURE_LOCAL_SOURCES=true` is explicitly set for a loopback host. Actual source privileges remain the database operator's responsibility.

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

Open `http://127.0.0.1:8000/` to select a previously registered connection, discover its catalog, save a draft, run a reference check, and publish. The screen is local-only. Select a connection and saved revision to resume work after a reload.

By default, the question box uses deterministic matching on relation names. Optionally enable the local AI integration described below to get model-generated source suggestions and a focused question. Suggestions remain unapproved and require owner review.

After discovering a connection, `POST /connections/{id}/onboarding/messages` gives deterministic, unapproved name-based suggestions. `PUT /connections/{id}/metrics/{metric_id}/draft` creates a revision; `POST .../verify` checks it against a fixed half-open date range and expected value, and `POST .../publish` publishes the latest passing revision. `GET .../revisions/{revision}` shows its definition, check, and status. The API documentation at `/docs` describes the fields.

Metrics can use row counts, distinct counts, sums, averages, and ratios of those aggregates on a single discovered table or view, with a DATE column and an optional fixed equality filter. Ratio numerator and denominator use the same source, date window, and filter; for different populations or sources, use an owner-approved reporting view. Joins, multiple fact sources, metric-specific time zones, and a full conversational UI are not yet supported. Define currencies and units explicitly: the system cannot infer whether a monetary column combines currencies. For the commerce fixture, the `billing.revenue_events` view can be summed with `event_date` and a fixed `currency` filter; January 2025 USD is 100. Product allocation is not defined. An owner must review the meaning of each definition and reference result.

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

“Last month” means the previous calendar month in the deployment-wide `CONTEXA_REPORTING_TIMEZONE` (an IANA time zone, default `UTC`), using the server clock. Effective dates and time zone are returned and stored with the intent. Metric names must match exactly, ignoring case; ambiguous names require an explicit ID. Other relative periods, multi-dimension breakdowns, multiple metrics, real identity and analyst permissions are not implemented. This remains a limited local prototype, not a general natural-language interface. An owner must have already checked currency, filters and source meaning. The browser's chat transcript is not restored on reload; accepted query intents and metric/snapshot versions are stored for provenance, but messages and result rows are not. Existing local setups need `alembic upgrade head` before using chat. Continue to use disposable data only.


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
