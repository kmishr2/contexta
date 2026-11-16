import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings
from app.main import create_app

META = os.getenv('CONTEXA_TEST_METADATA_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN, reason='disposable PostgreSQL test databases not configured')


def test_metric_formulas_checks_and_chat(monkeypatch):
    monkeypatch.setenv('CONTEXA_SOURCE_TEST', 'local-reader-only')
    settings = Settings(development_owner=True, metadata_url=META, allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True)
    source = {'label': 'Formula fixture', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_TEST', 'schemas': ['sales']}
    admin = create_engine(ADMIN)
    try:
        with admin.begin() as conn:
            conn.execute(text('CREATE TABLE sales.formula_test (event_date date, category text, numerator numeric, denominator numeric)'))
            conn.execute(text("INSERT INTO sales.formula_test VALUES ('2025-01-01','a',4,2),('2025-01-02','b',6,3),('2025-02-01','a',5,0),('2025-03-01','a',NULL,NULL),('2025-04-01','a',0,5),('2025-05-01','a',4,2),('2025-05-02','b',NULL,3)"))
            conn.execute(text('GRANT SELECT ON sales.formula_test TO contexta_reader'))
        with TestClient(create_app(settings)) as client:
            cid = client.post('/connections', json=source).json()['id']
            base = f'/connections/{cid}'
            assert client.post(base + '/discover').status_code == 200
            chat = client.post(base + '/chats').json()['id']
            common = {'schema_name': 'sales', 'relation': 'formula_test', 'date_column': 'event_date'}
            examples = [
                ('distinct_categories', {'aggregate': 'distinct_count', 'value_column': 'category'}, '2'),
                ('average_amount', {'aggregate': 'avg', 'value_column': 'numerator'}, '5'),
                ('ratio_sum', {'aggregate': 'ratio', 'numerator_aggregate': 'sum', 'value_column': 'numerator', 'denominator_aggregate': 'sum', 'denominator_column': 'denominator'}, '2'),
                ('ratio_count', {'aggregate': 'ratio', 'numerator_aggregate': 'sum', 'value_column': 'numerator', 'denominator_aggregate': 'count'}, '5'),
            ]
            for key, formula, expected in examples:
                base_metric = base + '/metrics/' + key
                definition = {'name': key, **common, **formula}
                saved = client.put(base_metric + '/draft', json=definition)
                assert saved.status_code == 201, saved.text
                check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': expected, 'provenance': 'independent fixture arithmetic'}
                verified = client.post(base_metric + '/verify', json=check)
                assert verified.status_code == 200 and verified.json()['check']['passed'], verified.text
                assert client.post(base_metric + '/publish', json={'revision': 1}).status_code == 200
                answer = client.post(f'/chats/{chat}/messages', json={'message': f'metric {key} from 2025-01-01 to 2025-02-01'}).json()
                assert answer['type'] == 'answer' and Decimal(answer['rows'][0][0]) == Decimal(expected)
                assert answer['data_status'] == 'value'
            invalid = client.put(base + '/metrics/invalid/draft', json={'name': 'bad', **common, 'aggregate': 'avg', 'value_column': 'category'})
            assert invalid.status_code == 422
            invalid = client.put(base + '/metrics/invalid/draft', json={'name': 'bad', **common, 'aggregate': 'ratio', 'numerator_aggregate': 'count', 'denominator_aggregate': 'sum'})
            assert invalid.status_code == 422
            def ask(start, end):
                return client.post(f'/chats/{chat}/messages', json={'message': f'metric ratio_sum from {start} to {end}'}).json()
            zero = ask('2025-02-01', '2025-03-01')
            assert zero['rows'] == [[None]] and zero['data_status'] == 'zero_denominator'
            missing = ask('2025-03-01', '2025-04-01')
            assert missing['rows'] == [[None]] and missing['data_status'] == 'missing_values'
            genuine_zero = ask('2025-04-01', '2025-05-01')
            assert Decimal(genuine_zero['rows'][0][0]) == 0 and genuine_zero['data_status'] == 'value'
            partial = ask('2025-05-01', '2025-06-01')
            assert partial['data_status'] == 'partial_values' and Decimal(partial['rows'][0][0]) == Decimal('0.8')
            empty = ask('2024-01-01', '2024-02-01')
            assert empty['rows'] == [[None]] and empty['data_status'] == 'no_matching_rows'
            null_metric = base + '/metrics/null_distinct'
            assert client.put(null_metric + '/draft', json={'name': 'null distinct', **common, 'aggregate': 'distinct_count', 'value_column': 'numerator'}).status_code == 201
            null_check = {'revision': 1, 'start': '2025-03-01', 'end': '2025-04-01', 'expected': '0', 'provenance': 'fixture'}
            null_result = client.post(null_metric + '/verify', json=null_check).json()['check']
            assert null_result['data_status'] == 'missing_values' and not null_result['passed']
            # A zero denominator cannot pass an ordinary numeric reference check.
            draft = client.put(base + '/metrics/ratio_sum/draft', json={'name': 'ratio_sum', **common, **examples[2][1]})
            check = {'revision': draft.json()['revision'], 'start': '2025-02-01', 'end': '2025-03-01', 'expected': '0', 'provenance': 'fixture'}
            result = client.post(base + '/metrics/ratio_sum/verify', json=check).json()['check']
            assert not result['passed'] and result['data_status'] == 'zero_denominator'
    finally:
        with admin.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS sales.formula_test'))
        admin.dispose()
