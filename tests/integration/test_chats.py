import os
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def test_chat_uses_published_definitions_and_scoped_context(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    monkeypatch.setattr('app.analytics.intent.reporting_today', lambda zone: date(2025, 2, 15))
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Commerce', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales', 'billing']}
    definition = {'name': 'Revenue USD', 'schema_name': 'billing', 'relation': 'revenue_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'dimensions': ['currency'], 'filter_column': 'currency', 'filter_value': 'USD'}
    admin = create_engine(ADMIN)
    try:
        with TestClient(create_app(settings)) as client:
            cid = client.post('/connections', json=source).json()['id']
            base = f'/connections/{cid}'
            assert client.post(base + '/discover').status_code == 200
            chat = client.post(base + '/chats').json()['id']
            ask = lambda message: client.post(f'/chats/{chat}/messages', json={'message': message})
            assert ask('metric revenue').json()['type'] == 'unsupported'
            assert client.put(base + '/metrics/revenue/draft', json=definition).status_code == 201
            assert ask('metric revenue').json()['type'] == 'unsupported'
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '100', 'provenance': 'fixture arithmetic'}
            assert client.post(base + '/metrics/revenue/verify', json=check).json()['check']['passed']
            assert client.post(base + '/metrics/revenue/publish', json={'revision': 1}).status_code == 200
            natural = ask('What was Revenue USD last month?').json()
            assert natural['rows'] == [['100.00']]
            assert natural['date_scope'] == {'start': '2025-01-01', 'end_exclusive': '2025-02-01', 'period': 'last_calendar_month', 'reporting_timezone': 'UTC'}
            assert ask('and last month?').json()['rows'] == [['100.00']]
            duplicate = base + '/metrics/revenue_alt'
            assert client.put(duplicate + '/draft', json=definition).status_code == 201
            assert client.post(duplicate + '/verify', json=check).json()['check']['passed']
            assert client.post(duplicate + '/publish', json={'revision': 1}).status_code == 200
            assert ask('What was Revenue USD last month?').json()['type'] == 'clarification'
            assert ask('last month').json()['type'] == 'clarification'
            assert ask('What was Revenue USD last month by product?').json()['type'] == 'unsupported'
            assert ask('last month').json()['type'] == 'clarification'
            assert ask('metric revenue').json()['type'] == 'clarification'
            answer = ask('from 2025-01-01 to 2025-02-01').json()
            assert answer['type'] == 'answer' and answer['rows'] == [['100.00']]
            assert answer['date_scope'] == {'start': '2025-01-01', 'end_exclusive': '2025-02-01', 'period': None, 'reporting_timezone': None}
            assert answer['metric']['revision'] == 1 and answer['query_run_id']
            assert 'USD' not in answer['sql']
            assert ask('from 2025-02-01 to 2025-03-01').json()['rows'] == [['-20.00']]
            empty = ask('from 2024-01-01 to 2024-02-01').json()
            assert empty['data_status'] == 'no_matching_rows' and empty['rows'] == [[None]]
            assert ask('metric revenue from 2025-01-01 to 2025-02-01 by product').json()['type'] == 'unsupported'
            other = client.post('/connections', json=source).json()['id']
            other_chat = client.post(f'/connections/{other}/chats').json()['id']
            assert client.post(f'/chats/{other_chat}/messages', json={'message': 'from 2025-01-01 to 2025-02-01'}).json()['type'] == 'clarification'
            assert client.post(f'/chats/{other_chat}/messages', json={'message': 'metric revenue from 2025-01-01 to 2025-02-01'}).json()['type'] == 'unsupported'
            with admin.begin() as conn:
                conn.execute(text('ALTER TABLE sales.orders ADD COLUMN chat_drift integer'))
            assert client.post(base + '/discover').status_code == 200
            assert ask('metric revenue from 2025-01-01 to 2025-02-01').json()['type'] == 'unsupported'
    finally:
        with admin.begin() as conn:
            conn.execute(text('ALTER TABLE sales.orders DROP COLUMN IF EXISTS chat_drift'))
        admin.dispose()
