import os
import pytest
from fastapi.testclient import TestClient
from app.core.settings import Settings
from app.llm.ollama import OnboardingSuggestion, SuggestedSource, LocalModelError
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
pytestmark = pytest.mark.skipif(not META or not os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL'), reason='disposable PostgreSQL test databases not configured')


def test_local_suggestions_are_bounded_and_fail_closed(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_onboarding=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Commerce', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    def fake(question, objects):
        assert len(objects) <= 12
        assert all(set(o) == {'schema', 'name', 'kind', 'columns'} for o in objects)
        assert all(set(c) == {'name', 'type'} for o in objects for c in o['columns'])
        assert all(o['schema'] == 'sales' for o in objects)
        return OnboardingSuggestion(question='Which orders count?', sources=[SuggestedSource(schema_name='sales', relation='orders', reason='Possible source')])
    monkeypatch.setattr('app.api.onboarding.local_suggest', fake)
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        base = f'/connections/{cid}'
        assert client.post(base + '/discover').status_code == 200
        result = client.post(base + '/onboarding/messages', json={'message': 'How many orders?'}).json()
        assert result['mode'] == 'local_ai' and result['question'] == 'Which orders count?'
        assert result['suggestions'][0]['relation'] == 'orders'
        def offline(*args):
            raise LocalModelError('sensitive error')
        monkeypatch.setattr('app.api.onboarding.local_suggest', offline)
        error = client.post(base + '/onboarding/messages', json={'message': 'orders'})
        assert error.status_code == 503 and 'sensitive' not in error.text
