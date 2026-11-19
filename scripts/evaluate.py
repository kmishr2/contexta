"""Evaluate disposable fixtures with a deterministic fake or local Ollama.

Run with: python -m scripts.evaluate --disposable --mode fake
"""
import argparse
import json
import os
import time
from contextlib import nullcontext
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.catalog.models import Chat, ConnectionRecord, MetricRevision, SchemaSnapshot
from app.core.settings import Settings
from app.evaluation.benchmark import CASES, answer_matches, fake_plan, plan_matches
from app.main import create_app


def validate_target(raw_url):
    if not raw_url:
        raise ValueError('Set CONTEXA_EVAL_METADATA_URL to the disposable metadata database')
    try:
        url = make_url(raw_url)
    except ArgumentError:
        raise ValueError('Invalid evaluation metadata URL') from None
    if (url.drivername != 'postgresql+psycopg' or url.host not in ('127.0.0.1', 'localhost')
            or url.port != 55439 or url.database != 'contexta_meta_test'):
        raise ValueError('Evaluation requires the disposable loopback contexta_meta_test database on port 55439')
    return url


def request(client, method, path, payload=None):
    response = client.request(method, path, json=payload)
    if response.status_code >= 400:
        # Never include response content, URLs with credentials, or driver errors.
        raise RuntimeError(f'Fixture setup failed at {path.split("/")[1]} (HTTP {response.status_code})')
    return response.json()


def setup(client, connection_ids):
    sources = {
        'commerce': {'label': 'Evaluation commerce', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_source_test', 'username': 'contexta_reader', 'credential_ref': 'CONTEXA_SOURCE_EVAL_COMMERCE', 'schemas': ['sales', 'billing']},
        'subscriptions': {'label': 'Evaluation subscriptions', 'host': '127.0.0.1', 'port': 55439, 'database': 'contexta_subscriptions_test', 'username': 'contexta_sub_reader', 'credential_ref': 'CONTEXA_SOURCE_EVAL_SUBSCRIPTIONS', 'schemas': ['crm', 'ledger', 'reporting']},
    }
    definitions = {
        'commerce': [('recognized', {'name': 'Recognized USD revenue', 'schema_name': 'billing', 'relation': 'revenue_events', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'event_date', 'filter_column': 'currency', 'filter_value': 'USD'}, '100')],
        'subscriptions': [
            ('recognized', {'name': 'Recognized USD revenue', 'schema_name': 'reporting', 'relation': 'recognized_invoices', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'booked_on', 'filter_column': 'currency', 'filter_value': 'USD'}, '120'),
            ('active_members', {'name': 'Live members joined', 'schema_name': 'reporting', 'relation': 'member_events', 'aggregate': 'distinct_count', 'value_column': 'member_key', 'date_column': 'joined_on', 'filter_column': 'member_state', 'filter_value': 'LIVE', 'dimensions': ['market']}, '2')],
    }
    ids = {}
    for name, source in sources.items():
        cid = request(client, 'POST', '/connections', source)['id']
        connection_ids.append(cid)
        ids[name] = cid
        request(client, 'POST', f'/connections/{cid}/verify')
        request(client, 'POST', f'/connections/{cid}/discover')
        for metric_id, definition, expected in definitions[name]:
            base = f'/connections/{cid}/metrics/{metric_id}'
            request(client, 'PUT', base + '/draft', definition)
            check = {'revision': 1, 'start': '2025-01-01', 'end': '2025-02-01', 'expected': expected, 'provenance': 'fixed fixture arithmetic'}
            if not request(client, 'POST', base + '/verify', check)['check']['passed']:
                raise RuntimeError('Fixture reference check did not pass')
            if metric_id == 'active_members':
                breakdown = {'revision': 1, 'dimension': 'market', 'start': '2025-01-01', 'end': '2025-02-01', 'expected': [{'dimension_value': 'North', 'expected': '1'}, {'dimension_value': 'South', 'expected': '1'}], 'provenance': 'fixed fixture arithmetic'}
                if not request(client, 'POST', base + '/verify-dimension', breakdown)['passed']:
                    raise RuntimeError('Fixture dimension check did not pass')
            request(client, 'POST', base + '/publish', {'revision': 1})
    return ids


def execute_cases(client, ids):
    chats, results = {}, []
    for case in CASES:
        key = case['chat']
        if key not in chats:
            chats[key] = request(client, 'POST', f"/connections/{ids[case['connection']]}/chats")['id']
        start = time.perf_counter()
        response = client.post(f"/chats/{chats[key]}/messages", json={'message': case['question']})
        kind = response.json().get('type') if response.status_code == 200 else 'error'
        passed = False
        executed = False
        matched_plan = None
        if case['expected'] == 'decline':
            passed = kind in ('clarification', 'unsupported')
        elif response.status_code == 200:
            matched_plan = plan_matches(case, response.json())
        if case['expected'] == 'answer' and matched_plan:
            # Never confirm an unexpected plan, even in disposable fixtures.
            confirmed = client.post(f"/chats/{chats[key]}/messages", json={'message': 'confirm'})
            if confirmed.status_code == 200 and confirmed.json().get('type') == 'answer':
                executed = True
                data = confirmed.json()
                passed = answer_matches(case, data)
        results.append({'id': case['id'], 'expected': case['expected'], 'observed': kind, 'passed': passed,
                        'executed': executed, 'plan_matched': matched_plan, 'http_status': response.status_code, 'latency_ms': round((time.perf_counter() - start) * 1000, 1)})
    answer_cases = [r for r in results if r['expected'] == 'answer']
    decline_cases = [r for r in results if r['expected'] == 'decline']
    return {'cases': results, 'summary': {'total': len(results), 'passed': sum(r['passed'] for r in results),
            'answers_correct': sum(r['passed'] for r in answer_cases), 'answers_total': len(answer_cases),
            'safe_declines': sum(r['passed'] for r in decline_cases), 'declines_total': len(decline_cases),
            'execution_successes': sum(r['executed'] for r in answer_cases),
            'model_usage': None}}


def cleanup(url, connection_ids):
    if not connection_ids:
        return
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as conn:
            conn.execute(delete(Chat).where(Chat.connection_id.in_(connection_ids)))
            conn.execute(delete(MetricRevision).where(MetricRevision.connection_id.in_(connection_ids)))
            conn.execute(delete(SchemaSnapshot).where(SchemaSnapshot.connection_id.in_(connection_ids)))
            conn.execute(delete(ConnectionRecord).where(ConnectionRecord.id.in_(connection_ids)))
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the Contexta benchmark against disposable fixtures only.')
    parser.add_argument('--disposable', action='store_true', required=True, help='Confirm the documented disposable fixture setup')
    parser.add_argument('--mode', choices=('fake', 'local'), default='fake')
    args = parser.parse_args(argv)
    try:
        url = validate_target(os.getenv('CONTEXA_EVAL_METADATA_URL'))
    except (ValueError, TypeError):
        parser.error('Set CONTEXA_EVAL_METADATA_URL to postgresql+psycopg on 127.0.0.1:55439/contexta_meta_test')
    settings = Settings(development_owner=True, identities=[], metadata_url=url.render_as_string(hide_password=False),
                        allowed_destinations=['127.0.0.1:55439'], allow_insecure_local_sources=True,
                        local_ai_chat=True, local_ai_onboarding=False)
    env = {'CONTEXA_SOURCE_EVAL_COMMERCE': 'local-reader-only', 'CONTEXA_SOURCE_EVAL_SUBSCRIPTIONS': 'local-sub-reader-only'}
    created = []
    try:
        with patch.dict(os.environ, env), (patch('app.api.chats.structured', fake_plan) if args.mode == 'fake' else nullcontext()):
            with TestClient(create_app(settings)) as client:
                ids = setup(client, created)
                report = execute_cases(client, ids)
        report['mode'] = args.mode
        print(json.dumps(report, indent=2))
        return 0 if report['summary']['passed'] == report['summary']['total'] else 1
    finally:
        cleanup(url, created)


if __name__ == '__main__':
    raise SystemExit(main())
