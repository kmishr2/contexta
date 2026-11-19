import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_owner_analysts_grants_and_private_chats(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    fixture_settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Access fixture', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    with TestClient(create_app(fixture_settings)) as client:
        first = client.post('/connections', json=source).json()['id']
        second = client.post('/connections', json=source).json()['id']
        base = f'/connections/{first}'
        assert client.post(base + '/discover').status_code == 200
        metric = base + '/metrics/orders'
        definition = {'name': 'Orders', 'schema_name': 'sales', 'relation': 'orders', 'aggregate': 'count', 'date_column': 'created_at'}
        assert client.put(metric + '/draft', json=definition).status_code == 201
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '2', 'provenance': 'fixture'}
        assert client.post(metric + '/verify', json=check).json()['check']['passed']
        assert client.post(metric + '/publish', json={'revision': 1}).status_code == 200
    tokens = {'owner': 'o' * 40, 'owner2': 'p' * 40, 'alice': 'a' * 40, 'bob': 'b' * 40}
    identities = [
        {'id': 'owner', 'role': 'owner', 'token_sha256': digest(tokens['owner'])},
        {'id': 'owner2', 'role': 'owner', 'token_sha256': digest(tokens['owner2'])},
        {'id': 'alice', 'role': 'analyst', 'token_sha256': digest(tokens['alice']), 'connections': [first]},
        {'id': 'bob', 'role': 'analyst', 'token_sha256': digest(tokens['bob']), 'connections': [first]},
    ]
    settings = Settings(identities=identities, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    headers = lambda name: {'Authorization': 'Bearer ' + tokens[name]}
    with TestClient(create_app(settings)) as client:
        assert client.get('/connections').status_code == 403
        assert client.get('/connections', headers=headers('alice')).json() == [{'id': first, 'label': 'Access fixture'}]
        assert len(client.get('/connections', headers=headers('owner')).json()) >= 2
        assert client.get(base + '/catalog', headers=headers('alice')).status_code == 403
        assert client.get(base + '/metrics', headers=headers('alice')).status_code == 403
        assert client.get(base + '/onboarding/conversations', headers=headers('alice')).status_code == 403
        assert client.post(base + '/discover', headers=headers('alice')).status_code == 403
        assert client.post(metric + '/publish', json={'revision': 1}, headers=headers('alice')).status_code == 403
        assert client.get(f'/connections/{second}/published-metrics', headers=headers('alice')).status_code == 404
        assert client.post(f'/connections/{second}/chats', headers=headers('alice')).status_code == 404
        assert client.get(base + '/published-metrics', headers=headers('alice')).json()[0]['id'] == 'orders'
        chat = client.post(base + '/chats', headers=headers('alice')).json()['id']
        msg = {'message': 'metric orders from 2025-01-01 to 2025-02-01'}
        answer = client.post(f'/chats/{chat}/messages', json=msg, headers=headers('alice')).json()
        assert answer['rows'] == [['2']] and 'sql' not in answer
        assert answer['metric']['definition'] == {'name': 'Orders'}
        assert client.get(base + '/chats/' + chat, headers=headers('bob')).status_code == 404
        assert client.get(base + '/chats/' + chat, headers=headers('owner')).status_code == 404
        assert client.post(f'/chats/{chat}/messages', json=msg, headers=headers('bob')).status_code == 404
        assert client.delete(base + '/chats/' + chat, headers=headers('bob')).status_code == 404
        assert client.get(base + '/chats/' + chat, headers=headers('alice')).json()['turns'][0]['response']['rows'] == [['2']]
        owner_chat = client.post(base + '/chats', headers=headers('owner')).json()['id']
        owner_answer = client.post(f'/chats/{owner_chat}/messages', json=msg, headers=headers('owner')).json()
        assert 'sql' in owner_answer and owner_answer['metric']['definition']['schema_name'] == 'sales'
        # A second owner cannot read a private onboarding conversation either.
        from app.llm.ollama import OnboardingSuggestion
        monkeypatch.setattr('app.api.onboarding.local_suggest', lambda question, objects, history: OnboardingSuggestion(question='Which orders?', sources=[]))
    with TestClient(create_app(settings.model_copy(update={'local_ai_onboarding': True}))) as client:
        conversation = client.post(base + '/onboarding/messages', json={'message': 'orders'}, headers=headers('owner')).json()['conversation_id']
        assert client.get(base + '/onboarding/conversations/' + conversation, headers=headers('owner2')).status_code == 404
        assert client.get(base + '/onboarding/conversations/' + conversation, headers=headers('owner')).status_code == 200
    # AI previews use the same analyst visibility as final answers.
    from datetime import date
    from app.llm.contracts import ChatPlan
    def planner(system, payload, response_model):
        return ChatPlan(kind='query', message='review', metric_id='orders', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1))
    monkeypatch.setattr('app.api.chats.structured', planner)
    with TestClient(create_app(settings.model_copy(update={'local_ai_chat': True}))) as client:
        ai_chat = client.post(base + '/chats', headers=headers('alice')).json()['id']
        preview = client.post(f'/chats/{ai_chat}/messages', json={'message': 'How many orders from 2025-01-01 to 2025-02-01?'}, headers=headers('alice')).json()
        assert preview['type'] == 'proposal' and preview['metric']['definition'] == {'name': 'Orders'}
        answer = client.post(f'/chats/{ai_chat}/messages', json={'message': 'confirm'}, headers=headers('alice')).json()
        assert answer['rows'] == [['2']] and 'sql' not in answer
        comparison = {'message': 'compare metric orders January 2025 with February 2025'}
        preview = client.post(f'/chats/{ai_chat}/messages', json=comparison, headers=headers('alice')).json()
        assert preview['type'] == 'comparison_proposal' and preview['metric']['definition'] == {'name': 'Orders'}
        result = client.post(f'/chats/{ai_chat}/messages', json={'message': 'confirm'}, headers=headers('alice')).json()
        assert result['type'] == 'comparison' and result['metric']['definition'] == {'name': 'Orders'}
        assert result['change']['reason'] == 'incomplete_data' and 'sql' not in result
        preview = client.post(f'/chats/{ai_chat}/messages', json={'message': 'trend metric orders from 2025-01-01 to 2025-03-01 by month'}, headers=headers('alice')).json()
        assert preview['type'] == 'trend_proposal' and preview['metric']['definition'] == {'name': 'Orders'}
        result = client.post(f'/chats/{ai_chat}/messages', json={'message': 'confirm'}, headers=headers('alice')).json()
        assert result['type'] == 'trend' and result['metric']['definition'] == {'name': 'Orders'} and 'sql' not in result
    # A role change re-applies visibility to previously stored owner responses.
    demoted = [dict(item) for item in identities]
    demoted[0] = {**demoted[0], 'role': 'analyst', 'connections': [first]}
    with TestClient(create_app(Settings(identities=demoted, metadata_url=META))) as client:
        past = client.get(base + '/chats/' + owner_chat, headers=headers('owner')).json()['turns'][0]['response']
        assert 'sql' not in past and past['metric']['definition'] == {'name': 'Orders'}
    # A revoked grant takes effect immediately when operator configuration changes.
    identities[2]['connections'] = []
    revoked = Settings(identities=identities, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    with TestClient(create_app(revoked)) as client:
        assert client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}, headers=headers('alice')).status_code == 404
        assert client.get(base + '/chats/' + chat, headers=headers('alice')).status_code == 404
