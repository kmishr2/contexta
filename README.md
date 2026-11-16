# Contexta

Contexta is a planned PostgreSQL onboarding and analytics chat application. This bootstrap provides an independent liveness endpoint and a local PostgreSQL service; it does not yet connect the application to a database.

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

Phase 2 starts with app-owned metadata migrations, connection policies and credential references, followed by scoped PostgreSQL discovery and integration tests.
