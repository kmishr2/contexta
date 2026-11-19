"""The same APIs onboard structurally different disposable databases."""
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
COMMERCE = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
SUBSCRIPTIONS = os.getenv('CONTEXA_TEST_SUBSCRIPTIONS_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not COMMERCE or not SUBSCRIPTIONS, reason='three disposable PostgreSQL databases not configured')


def test_two_databases_share_workflow_without_cross_connection_context(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_COMMERCE_FIXTURE', 'local-reader-only')
    monkeypatch.setenv('CONTEXA_SOURCE_SUB_FIXTURE', 'local-sub-reader-only')
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    common = {'host': '127.0.0.1', 'port': 55439}
    sources = [
        {**common, 'label': 'Commerce', 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_COMMERCE_FIXTURE', 'schemas': ['sales', 'billing']},
        {**common, 'label': 'Subscriptions', 'database': 'contexta_subscriptions_test', 'username': 'contexta_sub_reader', 'credential_ref': 'CONTEXA_SOURCE_SUB_FIXTURE', 'schemas': ['crm', 'ledger', 'reporting']},
    ]
    engines = [create_engine(COMMERCE), create_engine(SUBSCRIPTIONS)]
    try:
        # Independent reference SQL does not use the application compiler or reporting views.
        with engines[0].connect() as conn:
            commerce_expected = conn.execute(text("SELECT sum(amount) FROM billing.payment_attempts WHERE status = 'captured' AND currency = 'USD' AND captured_at >= '2025-01-01' AND captured_at < '2025-02-01'")).scalar_one()
        with engines[1].connect() as conn:
            subscriptions_expected = conn.execute(text("SELECT sum(amount) FROM (SELECT DISTINCT ON (invoice_key) amount, event_kind, currency, booked_on FROM ledger.invoice_events ORDER BY invoice_key, recorded_at DESC, event_key DESC) x WHERE event_kind = 'POSTED' AND currency = 'USD' AND booked_on >= '2025-01-01' AND booked_on < '2025-02-01'")).scalar_one()
            naive = conn.execute(text("SELECT sum(amount) FROM ledger.invoice_events WHERE event_kind = 'POSTED' AND currency = 'USD' AND booked_on >= '2025-01-01' AND booked_on < '2025-02-01'")).scalar_one()
        assert commerce_expected == Decimal('100') and subscriptions_expected == Decimal('120') and naive == Decimal('200')
        with TestClient(create_app(settings)) as client:
            ids = []
            for source in sources:
                response = client.post('/connections', json=source)
                assert response.status_code == 201, response.text
                cid = response.json()['id']
                ids.append(cid)
                assert client.post(f'/connections/{cid}/verify').json()['role'] == source['username']
                discovered = client.post(f'/connections/{cid}/discover')
                assert discovered.status_code == 200, discovered.text
                objects = {(o['schema'], o['name']) for o in discovered.json()['catalog']['objects']}
                assert all(schema != 'private_data' for schema, _ in objects)
                if source['label'] == 'Subscriptions':
                    assert {('crm', 'members'), ('ledger', 'members'), ('reporting', 'recognized_invoices')} <= objects
            definitions = [
                {'name': 'Recognized USD', 'schema_name': 'billing', 'relation': 'revenue_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'filter_column': 'currency', 'filter_value': 'USD'},
                {'name': 'Recognized USD', 'schema_name': 'reporting', 'relation': 'recognized_invoices', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'booked_on', 'filter_column': 'currency', 'filter_value': 'USD'},
            ]
            chats = []
            for cid, definition, expected in zip(ids, definitions, [commerce_expected, subscriptions_expected]):
                prefix = f'/connections/{cid}'
                assert client.put(prefix + '/metrics/recognized/draft', json=definition).status_code == 201
                check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': str(expected), 'provenance': 'independent fixture arithmetic'}
                assert client.post(prefix + '/metrics/recognized/verify', json=check).json()['check']['passed']
                assert client.post(prefix + '/metrics/recognized/publish', json={'revision': 1}).status_code == 200
                chat = client.post(prefix + '/chats').json()['id']
                chats.append(chat)
                answer = client.post(f'/chats/{chat}/messages', json={'message': 'metric recognized from 2025-01-01 to 2025-02-01'}).json()
                assert answer['type'] == 'answer' and Decimal(answer['rows'][0][0]) == expected
            # The same metric ID is resolved within each chat's connection, even on follow-up.
            for chat, expected in zip(chats, [commerce_expected, subscriptions_expected]):
                answer = client.post(f'/chats/{chat}/messages', json={'message': 'from 2025-01-01 to 2025-02-01'}).json()
                assert Decimal(answer['rows'][0][0]) == expected
            member_metric = f'/connections/{ids[1]}/metrics/active_members'
            definition = {'name': 'Live members', 'schema_name': 'reporting', 'relation': 'member_events', 'aggregate': 'distinct_count', 'value_column': 'member_key', 'date_column': 'joined_on', 'filter_column': 'member_state', 'filter_value': 'LIVE', 'dimensions': ['market']}
            assert client.put(member_metric + '/draft', json=definition).status_code == 201
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '2', 'provenance': 'fixture members'}
            assert client.post(member_metric + '/verify', json=check).json()['check']['passed']
            breakdown = {'revision': 1, 'dimension': 'market', 'start': '2025-01-01', 'end': '2025-02-01', 'expected': [{'dimension_value': 'North', 'expected': '1'}, {'dimension_value': 'South', 'expected': '1'}], 'provenance': 'fixture members'}
            assert client.post(member_metric + '/verify-dimension', json=breakdown).json()['passed']
            assert client.post(member_metric + '/publish', json={'revision': 1}).status_code == 200
            # Definitions and catalog IDs cannot be accessed through a different connection.
            assert client.get(f'/connections/{ids[0]}/metrics/active_members/revisions/1').status_code == 404
            denied = client.post('/connections', json={**sources[1], 'schemas': ['private_data']}).json()['id']
            assert client.post(f'/connections/{denied}/discover').status_code == 503
        with TestClient(create_app(Settings())) as client:
            assert client.post(f'/connections/{ids[1]}/chats').status_code == 403
    finally:
        for engine in engines:
            engine.dispose()
