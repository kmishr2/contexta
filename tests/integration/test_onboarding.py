import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
        suggestions = client.post(prefix + '/onboarding/messages', json={'message': 'What were revenue events last month?'}).json()['suggestions']
        assert suggestions[0] == {'schema': 'billing', 'relation': 'revenue_events', 'matched_terms': ['event', 'revenue']}
        assert client.post(prefix + '/onboarding/messages', json={'message': 'secret'}).json()['suggestions'] == []
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
        revisions = client.get(prefix + '/metrics').json()['revisions']
        assert [(r['revision'], r['state']) for r in revisions] == [(2, 'ready'), (1, 'superseded')]
        assert client.get(metric + '/revisions/2').json()['check']['passed']
        other_id = client.post('/connections', json=source).json()['id']
        other = f'/connections/{other_id}'
        assert client.post(other + '/discover').status_code == 200
        assert client.get(other + '/metrics').json()['revisions'] == []
        assert client.get(other + '/metrics/revenue/revisions/2').status_code == 404
        assert client.put(metric + '/draft', json=definition).json()['revision'] == 3
        admin = create_engine(os.environ['CONTEXA_TEST_SOURCE_ADMIN_URL'])
        try:
            with admin.begin() as conn:
                conn.execute(text('ALTER TABLE sales.orders ADD COLUMN onboarding_drift integer'))
            assert client.post(prefix + '/discover').status_code == 200
            assert client.get(metric + '/revisions/3').json()['state'] == 'stale'
            assert client.get(prefix + '/metrics').json()['revisions'][0]['state'] == 'stale'
            check['revision'] = 3
            assert client.post(metric + '/verify', json=check).status_code == 409
        finally:
            with admin.begin() as conn:
                conn.execute(text('ALTER TABLE sales.orders DROP COLUMN IF EXISTS onboarding_drift'))
            admin.dispose()
