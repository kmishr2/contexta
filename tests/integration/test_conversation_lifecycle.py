import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.llm.contracts import ChatPlan
from app.llm.ollama import OnboardingSuggestion
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def test_history_restore_delete_and_connection_isolation(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_chat=True, local_ai_onboarding=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'History', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    monkeypatch.setattr('app.api.onboarding.local_suggest', lambda question, objects, history: OnboardingSuggestion(question='Which records count?', sources=[]))
    monkeypatch.setattr('app.api.chats.structured', lambda system, payload, response_model: ChatPlan(kind='query', message='Review', metric_id='orders', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1)))
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        other = client.post('/connections', json=source).json()['id']
        base, other_base = f'/connections/{cid}', f'/connections/{other}'
        assert client.post(base + '/discover').status_code == 200
        assert client.post(other_base + '/discover').status_code == 200
        conversation = client.post(base + '/onboarding/messages', json={'message': 'Count orders'}).json()['conversation_id']
        assert client.delete(other_base + '/onboarding/conversations/' + conversation).status_code == 404
        assert client.get(base + '/onboarding/conversations/' + conversation).status_code == 200
        assert client.delete(base + '/onboarding/conversations/' + conversation).status_code == 204
        assert client.get(base + '/onboarding/conversations/' + conversation).status_code == 404
        definition = {'name': 'Orders', 'schema_name': 'sales', 'relation': 'orders', 'aggregate': 'count', 'date_column': 'created_at'}
        metric = base + '/metrics/orders'
        assert client.put(metric + '/draft', json=definition).status_code == 201
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '2', 'provenance': 'fixture'}
        assert client.post(metric + '/verify', json=check).json()['check']['passed']
        assert client.post(metric + '/publish', json={'revision': 1}).status_code == 200
        chat = client.post(base + '/chats').json()['id']
        assert client.get(other_base + '/chats/' + chat).status_code == 404
        assert client.delete(other_base + '/chats/' + chat).status_code == 404
        assert client.post(f'/chats/{chat}/messages', json={'message': 'How many orders?'}).json()['type'] == 'proposal'
        preview = client.get(base + '/chats/' + chat).json()
        assert preview['pending_confirmation'] and preview['turns'][0]['response']['type'] == 'proposal'
        assert client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}).json()['rows'] == [['2']]
        restored = client.get(base + '/chats/' + chat).json()
        assert not restored['pending_confirmation']
        assert [turn['message'] for turn in restored['turns']] == ['How many orders?', 'confirm']
        assert restored['turns'][1]['response']['rows'] == [['2']]
        assert client.get(base + '/chats').json()[0]['id'] == chat
        assert not client.get(other_base + '/chats').json()
        engine = create_engine(META)
        with engine.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM query_runs WHERE chat_id = :id'), {'id': chat}).scalar_one() == 1
        assert client.delete(base + '/chats/' + chat).status_code == 204
        assert client.get(base + '/chats/' + chat).status_code == 404
        assert client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}).status_code == 404
        with engine.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM query_runs WHERE chat_id = :id'), {'id': chat}).scalar_one() == 0
            assert conn.execute(text('SELECT count(*) FROM chat_turns WHERE chat_id = :id'), {'id': chat}).scalar_one() == 0
        engine.dispose()
    with TestClient(create_app(Settings())) as client:
        assert client.get(base + '/chats').status_code == 403
        assert client.delete(base + '/onboarding/conversations/' + conversation).status_code == 403


def test_chat_history_returns_most_recent_50(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'History limit', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        chat = client.post(f'/connections/{cid}/chats').json()['id']
        for index in range(52):
            assert client.post(f'/chats/{chat}/messages', json={'message': f'unsupported {index}'}).status_code == 200
        history = client.get(f'/connections/{cid}/chats/{chat}').json()
        assert history['has_more'] and len(history['turns']) == 50
        assert history['turns'][0]['message'] == 'unsupported 2'
        assert history['turns'][-1]['message'] == 'unsupported 51'
