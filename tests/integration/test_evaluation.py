import json
import os

import pytest
from sqlalchemy import create_engine, func, select

from app.catalog.models import ConnectionRecord
from scripts.evaluate import main

META = os.getenv('CONTEXA_TEST_METADATA_URL')
SUB = os.getenv('CONTEXA_TEST_SUBSCRIPTIONS_ADMIN_URL')
ADMIN = os.getenv('CONTEXA_TEST_SOURCE_ADMIN_URL')
pytestmark = pytest.mark.skipif(not META or not ADMIN or not SUB, reason='disposable PostgreSQL fixtures not configured')


def test_fake_benchmark_returns_results_and_removes_its_fixtures(monkeypatch, capsys):
    monkeypatch.setenv('CONTEXA_EVAL_METADATA_URL', META)
    engine = create_engine(META)
    try:
        with engine.connect() as conn:
            before = conn.scalar(select(func.count()).select_from(ConnectionRecord))
        assert main(['--disposable', '--mode', 'fake']) == 0
        output = capsys.readouterr().out
        report = json.loads(output)
        assert report['summary']['passed'] == 7 and report['summary']['total'] == 7
        assert report['summary']['answers_correct'] == 5 and report['summary']['safe_declines'] == 2
        assert 'local-reader-only' not in output and META not in output
        with engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(ConnectionRecord)) == before
    finally:
        engine.dispose()
