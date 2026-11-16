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


def test_relative_dates_names_and_ambiguity():
    from datetime import date
    metrics = [{'id': 'rev_usd', 'name': 'Revenue USD'}]
    result = interpret('What was Revenue USD last month?', None, None, metrics=metrics, today=date(2025, 1, 15), reporting_timezone='Asia/Kolkata')
    assert result['intent'].start == date(2024, 12, 1)
    assert result['intent'].end == date(2025, 1, 1)
    assert result['intent'].reporting_timezone == 'Asia/Kolkata'
    assert interpret('and last month?', {'metric_id': 'rev_usd'}, None, today=date(2024, 3, 1))['intent'].start == date(2024, 2, 1)
    assert interpret('What was Revenue USD last month by product?', None, None, metrics=metrics)['kind'] == 'unsupported'
    assert interpret('What was Revenue USD last month?', None, None, metrics=metrics + [{'id': 'second', 'name': 'Revenue USD'}])['kind'] == 'clarify'
    assert interpret('What was unknown last month?', None, None, metrics=metrics)['kind'] == 'unsupported'
