import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
SUB = os.getenv('CONTEXA_TEST_SUBSCRIPTIONS_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN or not SUB, reason='disposable PostgreSQL databases not configured')


def test_multiple_fixed_filters_are_shared_by_check_and_chat(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    monkeypatch.setenv('CONTEXA_SOURCE_SUB_TEST', 'local-sub-reader-only')
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    admin = create_engine(ADMIN)
    try:
        with admin.begin() as conn:
            conn.execute(text('CREATE TABLE sales.filter_fixture (day date, status text, currency text, note text, amount numeric)'))
            conn.execute(text("INSERT INTO sales.filter_fixture VALUES ('2025-01-01','captured','USD',NULL,100), ('2025-01-02','settled','USD',NULL,20), ('2025-01-03','failed','USD',NULL,300), ('2025-01-04','captured','EUR',NULL,400), ('2025-01-05','captured','USD','test',500)"))
            conn.execute(text('GRANT SELECT ON sales.filter_fixture TO contexta_reader'))
        common = {'host': '127.0.0.1', 'port': 55439}
        source = {**common, 'label': 'Filter fixture', 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
        with TestClient(create_app(settings)) as client:
            cid = client.post('/connections', json=source).json()['id']
            base = f'/connections/{cid}'
            assert client.post(base + '/discover').status_code == 200
            filters = [{'column': 'status', 'operator': 'in', 'values': ['captured', 'settled']}, {'column': 'currency', 'operator': 'eq', 'values': ['USD']}, {'column': 'note', 'operator': 'is_null', 'values': []}]
            definition = {'name': 'Eligible USD', 'schema_name': 'sales', 'relation': 'filter_fixture', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'day', 'fixed_filters': filters, 'dimensions': ['status']}
            metric = base + '/metrics/eligible'
            assert client.put(metric + '/draft', json=definition).status_code == 201
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '120', 'provenance': 'fixture arithmetic'}
            result = client.post(metric + '/verify', json=check)
            assert result.status_code == 200 and result.json()['check']['passed'], result.text
            dimension_check = {'revision': 1, 'dimension': 'status', 'start': '2025-01-01', 'end': '2025-02-01', 'expected': [{'dimension_value': 'captured', 'expected': '100'}, {'dimension_value': 'settled', 'expected': '20'}], 'provenance': 'fixture arithmetic'}
            assert client.post(metric + '/verify-dimension', json=dimension_check).json()['passed']
            assert client.post(metric + '/publish', json={'revision': 1}).status_code == 200
            chat = client.post(base + '/chats').json()['id']
            answer = client.post(f'/chats/{chat}/messages', json={'message': 'metric eligible from 2025-01-01 to 2025-02-01'}).json()
            assert Decimal(answer['rows'][0][0]) == 120
            assert 'captured' not in answer['sql'] and 'USD' not in answer['sql']
            assert client.get(metric + '/revisions/1').json()['definition']['fixed_filters'] == filters
            from datetime import date
            from app.llm.contracts import ChatPlan
            def planner(system, payload, response_model):
                return ChatPlan(kind='query', message='grouped', metric_id='eligible', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1), dimensions=['status'])
            monkeypatch.setattr('app.api.chats.structured', planner)
            with TestClient(create_app(settings.model_copy(update={'local_ai_chat': True}))) as ai_client:
                ai_chat = ai_client.post(base + '/chats').json()['id']
                assert ai_client.post(f'/chats/{ai_chat}/messages', json={'message': 'eligible by status from 2025-01-01 to 2025-02-01'}).json()['type'] == 'proposal'
                grouped = ai_client.post(f'/chats/{ai_chat}/messages', json={'message': 'confirm'}).json()
                assert grouped['rows'] == [['captured', '100'], ['settled', '20']]

            # SQL-looking user values remain bound values and cannot broaden a count.
            injected = {'name': 'Literal', 'schema_name': 'sales', 'relation': 'filter_fixture', 'aggregate': 'count', 'date_column': 'day', 'fixed_filters': [{'column': 'status', 'operator': 'eq', 'values': ["captured' OR TRUE --"]}]}
            assert client.put(base + '/metrics/literal/draft', json=injected).status_code == 201
            no_match = {**check, 'expected': '0'}
            verified = client.post(base + '/metrics/literal/verify', json=no_match).json()['check']
            assert verified['passed'] and verified['data_status'] == 'no_matching_rows'
            legacy = {'name': 'Legacy numeric filter', 'schema_name': 'sales', 'relation': 'filter_fixture', 'aggregate': 'count', 'date_column': 'day', 'filter_column': 'amount', 'filter_value': '500'}
            assert client.put(base + '/metrics/legacy_numeric/draft', json=legacy).status_code == 201
            assert client.post(base + '/metrics/legacy_numeric/verify', json={**check, 'expected': '1'}).json()['check']['passed']
            not_null = {'name': 'Test records', 'schema_name': 'sales', 'relation': 'filter_fixture', 'aggregate': 'count', 'date_column': 'day', 'fixed_filters': [{'column': 'note', 'operator': 'is_not_null', 'values': []}, {'column': 'amount', 'operator': 'in', 'values': ['500', '600']}]}
            assert client.put(base + '/metrics/non_null/draft', json=not_null).status_code == 201
            assert client.post(base + '/metrics/non_null/verify', json={**check, 'expected': '1'}).json()['check']['passed']
            sub = {**common, 'label': 'Subscriptions', 'database': 'contexta_subscriptions_test', 'username': 'contexta_sub_reader', 'credential_ref': 'CONTEXA_SOURCE_SUB_TEST', 'schemas': ['ledger']}
            sid = client.post('/connections', json=sub).json()['id']
            assert client.post(f'/connections/{sid}/discover').status_code == 200
            sub_def = {'name': 'Posted invoice events USD', 'schema_name': 'ledger', 'relation': 'invoice_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'booked_on', 'fixed_filters': [{'column': 'event_kind', 'operator': 'eq', 'values': ['POSTED']}, {'column': 'currency', 'operator': 'eq', 'values': ['USD']}]}
            sub_metric = f'/connections/{sid}/metrics/posted_events'
            assert client.put(sub_metric + '/draft', json=sub_def).status_code == 201
            assert client.post(sub_metric + '/verify', json={**check, 'expected': '200'}).json()['check']['passed']
    finally:
        with admin.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS sales.filter_fixture'))
        admin.dispose()
