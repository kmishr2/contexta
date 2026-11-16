from app.analytics.intent import interpret


def test_only_explicit_supported_grammar_executes():
    intent = interpret('metric revenue from 2025-01-01 to 2025-02-01', None, None)
    assert intent['kind'] == 'query'
    assert intent['intent'].metric_id == 'revenue'
    assert interpret('metric revenue', None, None)['kind'] == 'clarify'
    assert interpret('from 2025-02-01 to 2025-03-01', {'metric_id': 'revenue'}, None)['intent'].metric_id == 'revenue'
    assert interpret('from 2025-02-01 to 2025-03-01', {'metric_id': 'old'}, 'new')['intent'].metric_id == 'new'
    assert interpret('metric revenue from 2025-01-01 to 2025-02-01 by region', None, None)['kind'] == 'unsupported'
    assert interpret('metric revenue from 2025-02-30 to 2025-03-01', None, None)['kind'] == 'clarify'
    assert interpret('from 2025-01-01 to 2025-02-01', None, None)['kind'] == 'clarify'
