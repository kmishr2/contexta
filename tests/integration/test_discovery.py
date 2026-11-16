"""Requires dedicated, disposable databases; see README."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.settings import Settings
from app.main import create_app

META = os.getenv("CONTEXA_TEST_METADATA_URL")
ADMIN = os.getenv("CONTEXA_TEST_SOURCE_ADMIN_URL")
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason="disposable PostgreSQL test databases not configured")


def test_discovery_scope_rescan_and_permissions(monkeypatch):
    monkeypatch.setenv("CONTEXA_SOURCE_TEST", "local-reader-only")
    settings = Settings(development_owner=True, metadata_url=META,
                        allowed_destinations=["127.0.0.1:55439"], allow_insecure_local_sources=True)
    body = {"label": "Commerce", "host": "127.0.0.1", "port": 55439, "database": "contexta_source_test",
            "username": "contexta_reader", "credential_ref": "CONTEXA_SOURCE_TEST", "schemas": ["sales", "billing"]}
    admin = create_engine(ADMIN)
    reader = create_engine("postgresql+psycopg://contexta_reader:local-reader-only@127.0.0.1:55439/contexta_source_test")
    with reader.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("INSERT INTO sales.orders VALUES (99, 1, '2025-01-01')"))
    reader.dispose()
    try:
        with TestClient(create_app(settings)) as client:
            assert client.post('/connections', json={**body, "host": "example.com"}).status_code == 403
            created = client.post('/connections', json=body)
            assert created.status_code == 201, created.text
            cid = created.json()["id"]
            assert "credential_ref" not in created.json()
            verified = client.post(f'/connections/{cid}/verify')
            assert verified.json() == {"database": "contexta_source_test", "role": "contexta_reader"}
            first = client.post(f'/connections/{cid}/discover')
            assert first.status_code == 200, first.text
            data = first.json()
            objects = {(o['schema'], o['name']): o for o in data['catalog']['objects']}
            assert ('sales', 'orders') in objects and ('billing', 'orders') in objects
            assert ('sales', 'Quoted Items') in objects
            assert objects[('sales', 'Quoted Items')]['columns'][0]['name'] == 'Item ID'
            assert ('private_data', 'secret') not in objects
            assert objects[('billing', 'revenue_events')]['kind'] == 'view'
            assert client.post(f'/connections/{cid}/discover').json()['fingerprint'] == data['fingerprint']
            with admin.begin() as conn:
                conn.execute(text('ALTER TABLE sales.orders ADD COLUMN test_drift integer'))
                conn.execute(text('REVOKE SELECT ON billing.orders FROM contexta_reader'))
            changed = client.post(f'/connections/{cid}/discover').json()
            assert changed['changed'] is True
            assert ('billing', 'orders') not in {(o['schema'], o['name']) for o in changed['catalog']['objects']}
            assert client.get(f'/connections/{cid}/catalog').json()['fingerprint'] == changed['fingerprint']
            denied = client.post('/connections', json={**body, 'schemas': ['private_data']}).json()['id']
            assert client.post(f'/connections/{denied}/discover').status_code == 503
        with TestClient(create_app(Settings())) as client:
            assert client.post('/connections', json=body).status_code == 403
    finally:
        with admin.begin() as conn:
            conn.execute(text('ALTER TABLE sales.orders DROP COLUMN IF EXISTS test_drift'))
            conn.execute(text('GRANT SELECT ON billing.orders TO contexta_reader'))
        admin.dispose()
