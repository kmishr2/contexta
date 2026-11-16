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

Open `http://127.0.0.1:8000/` to select a previously registered connection, discover its catalog, save a draft, run a reference check, and publish. The screen is local-only and does not yet restore drafts across browser reloads.

After discovering a connection, `POST /connections/{id}/onboarding/messages` gives deterministic, unapproved name-based suggestions. `PUT /connections/{id}/metrics/{metric_id}/draft` creates a revision; `POST .../verify` checks it against a fixed half-open date range and expected value, and `POST .../publish` publishes the latest passing revision. `GET .../revisions/{revision}` shows its definition, check, and status. The API documentation at `/docs` describes the fields.

This first slice supports counts and sums on a single discovered table or view, a DATE column, and an optional fixed equality filter. It does not yet support joins, multiple fact sources, average, ratios, time zones, or a full conversational UI. Define currencies and units explicitly: the system cannot infer whether a monetary column combines currencies. For the commerce fixture, the `billing.revenue_events` view can be summed with `event_date` and a fixed `currency` filter; January 2025 USD is 100. Product allocation is not defined. An owner must review the meaning of each definition and reference result.

A rescan that changes any catalog fingerprint conservatively makes prior definitions stale for publication and review; affected-only invalidation is not implemented. Run a rescan after source changes. A source change made without a rescan is not automatically detected, so this prototype is not ready for production or real data.
