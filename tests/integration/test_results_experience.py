import os
from datetime import date
import pytest
from fastapi.testclient import TestClient
from app.core.settings import Settings
from app.llm.contracts import ChatPlan
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL fixtures not configured')


def test_clarification_survives_reload_and_answer_is_explained(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_chat=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Results', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    def model(system, payload, response_model):
        if not payload['clarification_context']:
            return ChatPlan(kind='clarify', message='Which dates?')
        assert payload['clarification_context'][0] == {'user': 'How many orders?', 'assistant': 'Which dates?'}
        assert payload['question'] == 'January 2025'
        return ChatPlan(kind='query', message='Review', metric_id='orders', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1))
    monkeypatch.setattr('app.api.chats.structured', model)
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        base = f'/connections/{cid}'
        assert client.post(base + '/discover').status_code == 200
        definition = {'name': 'Orders', 'schema_name': 'sales', 'relation': 'orders', 'aggregate': 'count', 'date_column': 'created_at'}
        assert client.put(base + '/metrics/orders/draft', json=definition).status_code == 201
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '2', 'provenance': 'fixture arithmetic'}
        assert client.post(base + '/metrics/orders/verify', json=check).json()['check']['passed']
        assert client.post(base + '/metrics/orders/publish', json={'revision': 1}).status_code == 200
        chat = client.post(base + '/chats').json()['id']
        assert client.post(f'/chats/{chat}/messages', json={'message': 'How many orders?'}).json()['type'] == 'clarification'
        assert client.get(base + '/chats/' + chat).json()['turns'][0]['response']['message'] == 'Which dates?'
        proposal = client.post(f'/chats/{chat}/messages', json={'message': 'January 2025'}).json()
        assert proposal['type'] == 'proposal' and proposal['metric']['id'] == 'orders'
        answer = client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}).json()
        assert answer['rows'] == [['2']] and answer['message'] == 'Orders: 2.'
        assert answer['scope']['start'] == '2025-01-01' and answer['scope']['end_exclusive'] == '2025-02-01'
        assert answer['scope']['filter_note'] == 'No fixed filters apply.'
        history = client.get(base + '/chats/' + chat).json()['turns']
        assert history[-1]['response']['message'] == 'Orders: 2.'

        # Even if the model invents a date, the user must supply it before a
        # query can be proposed. Additional conditions cannot be discarded.
        monkeypatch.setattr('app.api.chats.structured', lambda *args: ChatPlan(kind='query', message='Review', metric_id='orders', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1)))
        other = client.post(base + '/chats').json()['id']
        ask = lambda message: client.post(f'/chats/{other}/messages', json={'message': message}).json()
        assert ask('How many orders?')['type'] == 'clarification'
        assert ask('January 2025 but only Europe')['type'] == 'clarification'
        assert ask('confirm')['type'] == 'clarification'
        assert ask('How many orders?')['type'] == 'clarification'
        assert ask('January 2025')['type'] == 'proposal'
        assert ask('confirm')['rows'] == [['2']]
        assert ask('How many orders?')['type'] == 'clarification'
        assert ask('metric orders from 2025-01-01 to 2025-02-01')['type'] == 'proposal'
        assert ask('confirm')['rows'] == [['2']]

        def calendar_model(system, payload, response_model):
            window = payload['resolved_period']
            assert window == {'start': '2025-01-01', 'end': '2025-04-01'}
            return ChatPlan(kind='query', message='Review', metric_id='orders', period='explicit', start=date.fromisoformat(window['start']), end=date.fromisoformat(window['end']))
        monkeypatch.setattr('app.api.chats.structured', calendar_model)
        quarterly = client.post(base + '/chats').json()['id']
        proposal = client.post(f'/chats/{quarterly}/messages', json={'message': 'How many orders in Q1 2025?'}).json()
        assert proposal['type'] == 'proposal'
        assert proposal['scope']['period'] == 'calendar_quarter' and proposal['scope']['end_exclusive'] == '2025-04-01'
        assert client.post(f'/chats/{quarterly}/messages', json={'message': 'confirm'}).json()['rows'] == [['2']]

        # Comparisons execute only after confirmation and record both windows.
        compared = client.post(base + '/chats').json()['id']
        compare = lambda message: client.post(f'/chats/{compared}/messages', json={'message': message}).json()
        prompt = 'compare metric orders from 2025-01-01 to 2025-01-11 with from 2025-01-11 to 2025-02-01'
        preview = compare(prompt)
        assert preview['type'] == 'comparison_proposal' and preview['baseline_scope']['end_exclusive'] == '2025-01-11'
        assert client.get(base + '/chats/' + compared).json()['pending_confirmation']
        answer = compare('confirm')
        assert answer['type'] == 'comparison' and answer['baseline']['value'] == answer['current']['value'] == '1'
        assert answer['change'] == {'difference': '0', 'percent_change': '0.00', 'reason': None}
        assert answer['baseline']['query_run_id'] != answer['current']['query_run_id']
        assert compare('confirm')['type'] == 'clarification'
        assert compare('compare metric orders January 2025 with February 2025 by region')['type'] == 'clarification'
        assert compare('confirm')['type'] == 'clarification'
        assert compare(prompt)['type'] == 'comparison_proposal'

        trend_chat = client.post(base + '/chats').json()['id']
        trend_ask = lambda message: client.post(f'/chats/{trend_chat}/messages', json={'message': message}).json()
        trend_prompt = 'trend metric orders from 2025-01-01 to 2025-04-01 by month'
        trend_preview = trend_ask(trend_prompt)
        assert trend_preview['type'] == 'trend_proposal' and trend_preview['month_count'] == 3
        assert client.get(base + '/chats/' + trend_chat).json()['pending_confirmation']
        trend = trend_ask('confirm')
        assert trend['type'] == 'trend' and [row['value'] for row in trend['months']] == ['2', '0', '0']
        assert [row['data_status'] for row in trend['months']] == ['value', 'no_matching_rows', 'no_matching_rows']
        assert len({row['query_run_id'] for row in trend['months']}) == 3
        assert trend_ask('confirm')['type'] == 'clarification'
        assert trend_ask('trend metric orders 2025 by month where country is US')['type'] == 'clarification'
        assert trend_ask('confirm')['type'] == 'clarification'
        assert trend_ask('How did orders trend in 2025?')['type'] == 'clarification'
        assert trend_ask('confirm')['type'] == 'clarification'
        assert trend_ask(trend_prompt)['type'] == 'trend_proposal'
        assert client.post(base + '/discover').status_code == 200
        assert compare('confirm')['type'] == 'clarification'
        assert trend_ask('confirm')['type'] == 'clarification'
