import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.core.settings import Settings
from app.llm.contracts import ChatPlan
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def test_verified_breakdown_followup_and_bounds(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_chat=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Breakdown fixture', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    admin = create_engine(ADMIN)
    try:
        with admin.begin() as conn:
            conn.execute(text('CREATE TABLE sales.breakdown_test (event_date date, region text, amount numeric)'))
            conn.execute(text("INSERT INTO sales.breakdown_test VALUES ('2025-01-01','East',10),('2025-01-02','West',20)"))
            conn.execute(text('GRANT SELECT ON sales.breakdown_test TO contexta_reader'))
        with TestClient(create_app(settings)) as client:
            cid = client.post('/connections', json=source).json()['id']
            base = f'/connections/{cid}'
            assert client.post(base + '/discover').status_code == 200
            definition = {'name': 'Sales', 'schema_name': 'sales', 'relation': 'breakdown_test', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'dimensions': ['region']}
            metric = base + '/metrics/sales'
            assert client.put(metric + '/draft', json=definition).status_code == 201
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '30', 'provenance': 'fixture arithmetic'}
            assert client.post(metric + '/verify', json=check).json()['check']['passed']
            reference = {'revision': 1, 'dimension': 'region', 'start': '2025-01-01', 'end': '2025-02-01', 'expected': [{'dimension_value': 'East', 'expected': '10'}, {'dimension_value': 'West', 'expected': '99'}], 'provenance': 'trusted report'}
            assert not client.post(metric + '/verify-dimension', json=reference).json()['passed']
            reference['expected'][1]['expected'] = '20'
            assert client.post(metric + '/verify-dimension', json=reference).json()['passed']
            assert client.post(metric + '/publish', json={'revision': 1}).status_code == 200
            assert client.get(metric + '/revisions/1').json()['dimension_checks']['region']['passed']
            assert client.post(metric + '/verify-dimension', json=reference).status_code == 409
            def planner(system, payload, response_model):
                assert payload['metrics'][0]['dimensions'] == ['region']
                dims = ['region'] if 'region' in payload['question'] else []
                return ChatPlan(kind='query', message='proposed', metric_id='sales', period='explicit', start=date(2025,1,1), end=date(2025,2,1), dimensions=dims)
            monkeypatch.setattr('app.api.chats.structured', planner)
            chat = client.post(base + '/chats').json()['id']
            ask = lambda q: client.post(f'/chats/{chat}/messages', json={'message': q})
            assert ask('sales overall').json()['type'] == 'proposal'
            assert ask('confirm').json()['rows'] == [['30']]
            proposal = ask('and by region?').json()
            assert proposal['dimensions'] == ['region']
            answer = ask('confirm').json()
            assert answer['columns'] == ['region', 'value']
            assert answer['rows'] == [['East','10'], ['West','20']]
            assert answer['row_statuses'] == ['value', 'value'] and not answer['truncated']
            def bad(system, payload, response_model):
                return ChatPlan(kind='query', message='bad', metric_id='sales', period='last_month', dimensions=['amount'])
            monkeypatch.setattr('app.api.chats.structured', bad)
            assert ask('by amount').json()['type'] == 'unsupported'
            monkeypatch.setattr('app.api.chats.structured', planner)
            with admin.begin() as conn:
                conn.execute(text("INSERT INTO sales.breakdown_test SELECT '2025-01-03'::date, 'R' || n::text, 1 FROM generate_series(1, 101) AS n"))
            assert ask('by region').json()['type'] == 'proposal'
            capped = ask('confirm').json()
            assert capped['truncated'] is True and capped['row_count'] == 100
            assert client.put(metric + '/draft', json=definition).status_code == 201
            reference['revision'] = 2
            too_many = client.post(metric + '/verify-dimension', json=reference).json()
            assert not too_many['passed'] and too_many['truncated']
            # Oversized group labels must not escape the response byte budget.
            with admin.begin() as conn:
                conn.execute(text("INSERT INTO sales.breakdown_test VALUES ('2025-01-04', repeat('!', 300000), 1)"))
            reference['expected'] = [{'dimension_value': 'East', 'expected': '10'}]
            assert client.post(metric + '/verify-dimension', json=reference).status_code == 413
    finally:
        with admin.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS sales.breakdown_test'))
        admin.dispose()
