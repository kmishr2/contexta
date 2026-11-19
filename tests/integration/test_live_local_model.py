"""Optional smoke test: requires an already-running local model."""
import os
import pytest
from app.llm.ollama import suggest

pytestmark = pytest.mark.skipif(os.getenv('CONTEXA_TEST_LIVE_OLLAMA') != '1', reason='local model smoke test is opt-in')


def test_local_model_structured_suggestion():
    catalog = [{'schema': 'sales', 'name': 'orders', 'kind': 'table', 'columns': [{'name': 'created_at', 'type': 'DATE'}, {'name': 'id', 'type': 'INTEGER'}]}]
    result = suggest('How many orders did we have?', catalog)
    assert result.question
    assert all((item.schema_name, item.relation) == ('sales', 'orders') for item in result.sources)


def test_real_model_draft_and_query_plan():
    from app.llm.contracts import ChatPlan, DraftProposal
    from app.llm.ollama import structured
    catalog = [{'schema': 'sales', 'name': 'orders', 'kind': 'table', 'columns': [{'name': 'created_at', 'type': 'DATE'}, {'name': 'id', 'type': 'INTEGER'}]}]
    proposal = structured('Help an owner define one metric using only supplied catalog objects and column names. Only propose a definition if the user has stated the source, aggregation, date column, and any necessary filters and business rules. Otherwise ask one focused clarification. Never invent business rules, joins, columns or SQL. The proposal is unapproved. If kind is proposal, definition MUST be a complete non-null object. If you cannot provide all required definition fields, use kind clarify with a null definition and a specific question. Return the specified JSON schema.', {'request': 'Count all rows from sales.orders using created_at as the date. There are no exclusions.', 'catalog': catalog}, DraftProposal)
    assert proposal.kind in {'proposal', 'clarify', 'unsupported'}
    if proposal.definition:
        assert proposal.definition.schema_name == 'sales' and proposal.definition.relation == 'orders'
    plan = structured('Interpret the user question using only supplied approved metric IDs. Return a structured query only when the request is unambiguous and fully supported. Supported query: one metric, no breakdowns, no additional filters, with an explicit half-open date window or last_month. If a breakdown or filter is requested, return unsupported; never omit it. For kind query, metric_id and period must be non-null; explicit periods also need start and end dates. For clarify or unsupported, query fields must be null and arrays empty. Never write SQL.', {'question': 'What was revenue last month?', 'metrics': [{'id': 'revenue', 'name': 'Revenue'}], 'previous_intent': None}, ChatPlan)
    assert plan.kind in {'query', 'clarify', 'unsupported'}
    if plan.kind == 'query':
        assert plan.metric_id == 'revenue' and plan.period == 'last_month' and not plan.filters and not plan.dimensions


def test_real_local_model_onboarding_and_chat_end_to_end(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.settings import Settings
    from app.main import create_app
    meta = os.getenv('CONTEXA_TEST_METADATA_URL')
    if not meta or not os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL'):
        pytest.skip('disposable PostgreSQL fixture not configured')
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_onboarding=True, local_ai_chat=True, metadata_url=meta, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Live model fixture', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        base = f'/connections/{cid}'
        assert client.post(base + '/discover').status_code == 200
        response = client.post(base + '/onboarding/propose', json={'message': 'Count all rows from sales.orders using created_at as the date. There are no exclusions.'})
        assert response.status_code == 200, response.text
        assert response.json()['kind'] in {'proposal', 'clarify', 'unsupported'}
        definition = {'name': 'Orders', 'schema_name': 'sales', 'relation': 'orders', 'aggregate': 'count', 'date_column': 'created_at', 'dimensions': ['customer_id']}
        assert client.put(base + '/metrics/orders/draft', json=definition).status_code == 201
        check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '2', 'provenance': 'fixture arithmetic'}
        assert client.post(base + '/metrics/orders/verify', json=check).json()['check']['passed']
        dimension_check = {'revision': 1, 'dimension': 'customer_id', 'start': '2025-01-01', 'end': '2025-02-01', 'expected': [{'dimension_value': '101', 'expected': '1'}, {'dimension_value': '102', 'expected': '1'}], 'provenance': 'fixture arithmetic'}
        assert client.post(base + '/metrics/orders/verify-dimension', json=dimension_check).json()['passed']
        assert client.post(base + '/metrics/orders/publish', json={'revision': 1}).status_code == 200
        chat = client.post(base + '/chats').json()['id']
        result = client.post(f'/chats/{chat}/messages', json={'message': 'How many orders were there from 2025-01-01 to 2025-02-01? The end date is exclusive.'})
        assert result.status_code == 200, result.text
        assert result.json()['type'] in {'proposal', 'clarification'}, result.text
        if result.json()['type'] == 'proposal':
            assert result.json()['dimensions'] == []
            confirmed = client.post(f'/chats/{chat}/messages', json={'message': 'confirm'})
            assert confirmed.status_code == 200 and confirmed.json()['rows'] == [['2']]
        followup = client.post(f'/chats/{chat}/messages', json={'message': 'Show orders by customer_id from 2025-01-01 to 2025-02-01. The end date is exclusive.'})
        assert followup.status_code == 200 and followup.json()['type'] == 'proposal', followup.text
        assert followup.json()['dimensions'] == ['customer_id']
        breakdown = client.post(f'/chats/{chat}/messages', json={'message': 'confirm'})
        assert breakdown.status_code == 200 and breakdown.json()['rows'] == [['101', '1'], ['102', '1']]
        followup2 = client.post(f'/chats/{chat}/messages', json={'message': 'And by customer_id?'})
        assert followup2.status_code == 200 and followup2.json()['type'] == 'proposal', followup2.text
        assert followup2.json()['date_scope']['start'] == '2025-01-01'
        assert client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}).json()['rows'] == [['101', '1'], ['102', '1']]
        quarter = client.post(f'/chats/{chat}/messages', json={'message': 'How many orders in Q1 2025?'})
        assert quarter.status_code == 200 and quarter.json()['type'] == 'proposal', quarter.text
        assert quarter.json()['date_scope']['start'] == '2025-01-01'
        assert quarter.json()['date_scope']['end_exclusive'] == '2025-04-01'
        assert client.post(f'/chats/{chat}/messages', json={'message': 'confirm'}).json()['rows'] == [['2']]
        unsupported = client.post(f'/chats/{chat}/messages', json={'message': 'Show orders by region last month.'})
        assert unsupported.status_code == 200 and unsupported.json()['type'] in {'unsupported', 'clarification'}, unsupported.text


def test_real_model_multi_turn_onboarding(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.settings import Settings
    from app.main import create_app
    meta = os.getenv('CONTEXA_TEST_METADATA_URL')
    if not meta or not os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL'):
        pytest.skip('disposable PostgreSQL fixture not configured')
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_onboarding=True, metadata_url=meta, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Live dialogue', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    with TestClient(create_app(settings)) as client:
        cid = client.post('/connections', json=source).json()['id']
        base = f'/connections/{cid}'
        assert client.post(base + '/discover').status_code == 200
        first = client.post(base + '/onboarding/messages', json={'message': 'I want to count orders.'})
        assert first.status_code == 200, first.text
        conversation = first.json()['conversation_id']
        second = client.post(base + '/onboarding/messages', json={'message': 'Count every row in sales.orders, use created_at, with no exclusions.', 'conversation_id': conversation})
        assert second.status_code == 200 and second.json()['conversation_id'] == conversation, second.text
        history = client.get(base + '/onboarding/conversations/' + conversation).json()['turns']
        assert len(history) == 2 and history[0]['owner'] == 'I want to count orders.'
        proposal = client.post(base + '/onboarding/propose', json={'message': 'Please propose the metric.', 'conversation_id': conversation})
        assert proposal.status_code == 200, proposal.text
        assert proposal.json()['kind'] in {'proposal', 'clarify', 'unsupported'}
