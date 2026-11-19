import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL fixtures not configured')


def test_comparison_uses_single_snapshot_and_fails_closed(monkeypatch):
    from app.analytics.compiler import build_metric_query
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, local_ai_chat=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Comparison fixture', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    engine = create_engine(ADMIN)
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE sales.comparison_snapshot_test (event_date date)'))
            conn.execute(text("INSERT INTO sales.comparison_snapshot_test VALUES ('2025-01-05'), ('2025-02-05')"))
            conn.execute(text('GRANT SELECT ON sales.comparison_snapshot_test TO contexta_reader'))
        with TestClient(create_app(settings)) as client:
            base = '/connections/' + client.post('/connections', json=source).json()['id']
            assert client.post(base + '/discover').status_code == 200
            metric = base + '/metrics/snapshot_count'
            definition = {'name': 'Snapshot count', 'schema_name': 'sales', 'relation': 'comparison_snapshot_test', 'aggregate': 'count', 'date_column': 'event_date'}
            assert client.put(metric + '/draft', json=definition).status_code == 201
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': '1', 'provenance': 'fixture arithmetic'}
            assert client.post(metric + '/verify', json=check).json()['check']['passed']
            assert client.post(metric + '/publish', json={'revision': 1}).status_code == 200
            chat = client.post(base + '/chats').json()['id']
            ask = lambda message: client.post(f'/chats/{chat}/messages', json={'message': message})
            assert ask('compare metric snapshot_count January 2025 with February 2025').json()['type'] == 'comparison_proposal'
            count = 0
            def concurrent_insert(*args, **kwargs):
                nonlocal count
                count += 1
                if count == 2:
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO sales.comparison_snapshot_test VALUES ('2025-02-06')"))
                return build_metric_query(*args, **kwargs)
            monkeypatch.setattr('app.analytics.execute.build_metric_query', concurrent_insert)
            result = ask('confirm').json()
            assert result['baseline']['value'] == '1' and result['current']['value'] == '1'
            monkeypatch.setattr('app.analytics.execute.build_metric_query', build_metric_query)
            assert ask('compare metric snapshot_count January 2025 with February 2025').json()['type'] == 'comparison_proposal'
            result = ask('confirm').json()
            assert result['baseline']['value'] == '1' and result['current']['value'] == '2'
            assert result['change']['difference'] == '1' and result['change']['percent_change'] == '100.00'
            assert ask('trend metric snapshot_count from 2025-01-01 to 2025-03-01 by month').json()['type'] == 'trend_proposal'
            count = 0
            monkeypatch.setattr('app.analytics.execute.build_metric_query', concurrent_insert)
            trend = ask('confirm').json()
            assert [month['value'] for month in trend['months']] == ['1', '2']
            monkeypatch.setattr('app.analytics.execute.build_metric_query', build_metric_query)
            from app.sources.postgres.discovery import SourcePolicyError
            assert ask('compare metric snapshot_count January 2025 with February 2025').json()['type'] == 'comparison_proposal'
            def source_failure(*args):
                raise SourcePolicyError('private detail')
            monkeypatch.setattr('app.api.chats.execute_metrics', source_failure)
            failed = ask('confirm')
            assert failed.status_code == 503 and 'private detail' not in failed.text
            assert ask('confirm').json()['type'] == 'clarification'
            assert ask('trend metric snapshot_count from 2025-01-01 to 2025-03-01 by month').json()['type'] == 'trend_proposal'
            failed = ask('confirm')
            assert failed.status_code == 503 and 'private detail' not in failed.text
            assert ask('confirm').json()['type'] == 'clarification'
    finally:
        with engine.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS sales.comparison_snapshot_test'))
        engine.dispose()
