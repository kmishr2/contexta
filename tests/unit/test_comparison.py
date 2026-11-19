from datetime import date

from app.analytics.comparison import comparison_change, parse_comparison


def test_only_complete_comparisons_are_parsed():
    today = date(2025, 5, 1)
    baseline, current = parse_comparison('compare metric orders January 2025 with February 2025', today)
    assert (baseline.start, baseline.end) == (date(2025, 1, 1), date(2025, 2, 1))
    assert (current.start, current.end) == (date(2025, 2, 1), date(2025, 3, 1))
    assert parse_comparison('compare metric orders Q1 2024 vs Q1 2025?', today)[1].end == date(2025, 4, 1)
    assert parse_comparison('compare metric orders from 2025-01-01 to 2025-02-01 with from 2025-02-01 to 2025-03-01', today)
    for text in ['compare metric orders January 2025 with February 2025 by region',
                 'compare metric orders January 2025 with February 2025 where country is US',
                 'compare metric orders last month with 2025',
                 'compare metric orders 9999 with 2025',
                 'compare metric orders 2025 with 2026 versus 2027',
                 'compare metric orders from 2025-02-01 to 2025-01-01 with 2025']:
        assert parse_comparison(text, today) is None


def test_change_handles_zero_negative_and_incomplete_values():
    value = lambda amount: {'value': amount, 'data_status': 'value'}
    assert comparison_change(value('10'), value('15')) == {'difference': '5', 'percent_change': '50.00', 'reason': None}
    assert comparison_change(value('-10'), value('-5'))['percent_change'] == '50.00'
    assert comparison_change(value('0'), value('5')) == {'difference': '5', 'percent_change': None, 'reason': 'zero_baseline'}
    assert comparison_change({'value': None, 'data_status': 'missing_values'}, value('5'))['reason'] == 'incomplete_data'
    assert comparison_change({'value': '10', 'data_status': 'partial_values'}, value('5'))['reason'] == 'incomplete_data'
    assert comparison_change(value('NaN'), value('5'))['reason'] == 'unrepresentable'
