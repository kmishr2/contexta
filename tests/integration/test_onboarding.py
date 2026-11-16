import os
import pytest
from fastapi.testclient import TestClient
from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
pytestmark = pytest.mark.skipif(not META or not os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL'), reason='disposable PostgreSQL test databases not configured')


def test_owner_draft_verify_publish_and_stale(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Commerce', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales', 'billing']}
    definition = {'name': 'Revenue', 'schema_name': 'billing', 'relation': 'revenue_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'dimensions': ['currency'], 'filter_column': 'currency', 'filter_value': 'USD'}
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        prefix = f'/connections/{cid}'
        assert client.post(prefix + '/discover').status_code == 200
        assert client.post(prefix + '/onboarding/messages', json={'message': 'revenue'}).json()['suggestions']
        metric = prefix + '/metrics/revenue'
        draft = client.put(metric + '/draft', json=definition)
        assert draft.status_code == 201, draft.text
        assert client.post(metric + '/publish', json={'revision': 1}).status_code == 409
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '1', 'provenance': 'fixture arithmetic'}
        assert not client.post(metric + '/verify', json=check).json()['check']['passed']
        assert client.post(metric + '/publish', json={'revision': 1}).status_code == 409
        check['expected'] = '100'
        response = client.post(metric + '/verify', json=check)
        assert response.status_code == 200, response.text
        assert response.json()['check']['passed']
        assert client.post(metric + '/publish', json={'revision': 1}).json()['state'] == 'ready'
        assert client.put(metric + '/draft', json={**definition, 'value_column': 'missing'}).status_code == 422
        assert client.put(metric + '/draft', json=definition).json()['revision'] == 2
        assert client.post(metric + '/publish', json={'revision': 1}).status_code == 409
        check['revision'] = 2
        assert client.post(metric + '/verify', json=check).json()['check']['passed']
        assert client.post(metric + '/publish', json={'revision': 2}).json()['state'] == 'ready'
