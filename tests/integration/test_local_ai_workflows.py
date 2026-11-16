import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.llm.contracts import ChatPlan, DraftProposal
from app.llm.ollama import LocalModelError
from app.main import create_app
from app.onboarding.metrics import Definition

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def test_ai_proposal_preview_confirmation_and_revalidation(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_onboarding=True, local_ai_chat=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Commerce AI', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales', 'billing']}
    definition = {'name': 'USD revenue', 'schema_name': 'billing', 'relation': 'revenue_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'dimensions': ['currency'], 'filter_column': 'currency', 'filter_value': 'USD'}
    def draft_model(system, payload, response_model):
        assert all(set(o) == {'schema', 'name', 'kind', 'columns'} for o in payload['catalog'])
        return DraftProposal(kind='proposal', message='Review the proposed definition.', definition=Definition(**definition))
    monkeypatch.setattr('app.api.onboarding.structured', draft_model)
    def plan_model(system, payload, response_model):
        assert all(set(m) == {'id', 'name', 'dimensions'} for m in payload['metrics'])
        return ChatPlan(kind='query', message='Suggested query', metric_id='revenue', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1))
    monkeypatch.setattr('app.api.chats.structured', plan_model)
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        base = f'/connections/{cid}'
        assert client.post(base + '/discover').status_code == 200
        proposal = client.post(base + '/onboarding/propose', json={'message': 'Sum the USD revenue events using event date.'})
        assert proposal.status_code == 200 and proposal.json()['kind'] == 'proposal'
        assert client.get(base + '/metrics').json()['revisions'] == []
        draft = client.put(base + '/metrics/revenue/draft', json=proposal.json()['definition'])
        assert draft.status_code == 201
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '100', 'provenance': 'fixture arithmetic'}
        assert client.post(base + '/metrics/revenue/verify', json=check).json()['check']['passed']
        assert client.post(base + '/metrics/revenue/publish', json={'revision': 1}).status_code == 200
        chat = client.post(base + '/chats').json()['id']
        ask = lambda msg: client.post(f'/chats/{chat}/messages', json={'message': msg})
        pending = ask('How much was January revenue?').json()
        assert pending['type'] == 'proposal' and pending['metric']['definition']['filter_value'] == 'USD'
        engine = create_engine(META)
        with engine.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM query_runs WHERE chat_id = :id'), {'id': chat}).scalar_one() == 0
        engine.dispose()
        result = ask('confirm').json()
        assert result['type'] == 'answer' and result['rows'] == [['100.00']]
        assert ask('confirm').json()['type'] == 'clarification'
        assert ask('try again').json()['type'] == 'proposal'
        assert client.post(base + '/discover').status_code == 200
        assert ask('confirm').json()['type'] == 'clarification'
        assert ask('try again').json()['type'] == 'proposal'
        def unsupported(system, payload, response_model):
            return ChatPlan(kind='query', message='group', metric_id='revenue', period='last_month', dimensions=['product'])
        monkeypatch.setattr('app.api.chats.structured', unsupported)
        assert ask('by product').json()['type'] == 'unsupported'
        assert ask('confirm').json()['type'] == 'clarification'
        def invalid_metric(system, payload, response_model):
            return ChatPlan(kind='query', message='bad metric', metric_id='other_connection', period='last_month')
        monkeypatch.setattr('app.api.chats.structured', invalid_metric)
        assert ask('another').json()['type'] == 'unsupported'
        monkeypatch.setattr('app.api.chats.structured', plan_model)
        assert ask('try again').json()['type'] == 'proposal'
        def offline(*args):
            raise LocalModelError('sensitive detail')
        monkeypatch.setattr('app.api.chats.structured', offline)
        failure = ask('retry')
        assert failure.status_code == 503 and 'sensitive' not in failure.text
        assert ask('confirm').json()['type'] == 'clarification'
        def wrong_source(system, payload, response_model):
            return DraftProposal(kind='proposal', message='bad', definition=Definition(**{**definition, 'relation': 'not_in_catalog'}))
        monkeypatch.setattr('app.api.onboarding.structured', wrong_source)
        assert client.post(base + '/onboarding/propose', json={'message': 'something'}).status_code == 503
