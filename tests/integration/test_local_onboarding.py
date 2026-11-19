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
    seen_history = []
    def fake(question, objects, history):
        seen_history.append(history)
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
        conversation = result['conversation_id']
        continued = client.post(base + '/onboarding/messages', json={'message': 'Exclude canceled orders.', 'conversation_id': conversation})
        assert continued.status_code == 200 and continued.json()['conversation_id'] == conversation
        assert seen_history[0] == []
        assert seen_history[1] == [{'owner': 'How many orders?', 'assistant': 'Which orders count?'}]
        from app.llm.contracts import DraftProposal
        def draft_model(system, payload, response_model):
            assert payload['history'][1]['owner'] == 'Exclude canceled orders.'
            return DraftProposal(kind='clarify', message='Which date should we use?')
        monkeypatch.setattr('app.api.onboarding.structured', draft_model)
        proposed = client.post(base + '/onboarding/propose', json={'message': 'Help define orders.', 'conversation_id': conversation})
        assert proposed.json()['kind'] == 'clarify'
        assert len(client.get(base + '/onboarding/conversations/' + conversation).json()['turns']) == 2
        assert client.get(base + '/onboarding/conversations').json()[0]['turn_count'] == 2
        for number in range(10):
            assert client.post(base + '/onboarding/messages', json={'message': f'answer {number}', 'conversation_id': conversation}).status_code == 200
        assert client.post(base + '/onboarding/messages', json={'message': 'too many', 'conversation_id': conversation}).status_code == 409
        assert len(client.get(base + '/onboarding/conversations/' + conversation).json()['turns']) == 12
        other = client.post('/connections', json=source).json()['id']
        assert client.post(f'/connections/{other}/discover').status_code == 200
        assert client.get(f'/connections/{other}/onboarding/conversations/{conversation}').status_code == 404
        assert client.post(f'/connections/{other}/onboarding/messages', json={'message':'test','conversation_id':conversation}).status_code == 404
        assert client.post(base + '/discover').status_code == 200
        assert client.get(base + '/onboarding/conversations/' + conversation).json()['stale']
        assert client.post(base + '/onboarding/messages', json={'message':'test','conversation_id':conversation}).status_code == 409
        assert result['suggestions'][0]['relation'] == 'orders'
        def offline(*args):
            raise LocalModelError('sensitive error')
        monkeypatch.setattr('app.api.onboarding.local_suggest', offline)
        error = client.post(base + '/onboarding/messages', json={'message': 'orders'})
        assert error.status_code == 503 and 'sensitive' not in error.text
