from datetime import date
from app.analytics.explain import explain_result, scope_summary
from app.analytics.intent import QueryIntent
from app.onboarding.metrics import Definition


def test_explanation_distinguishes_zero_missing_and_no_rows():
    definition = Definition(name='Revenue', schema_name='s', relation='r', aggregate='sum', value_column='amount', date_column='day', filter_column='currency', filter_value='USD')
    intent = QueryIntent(metric_id='revenue', start=date(2025, 1, 1), end=date(2025, 2, 1))
    assert explain_result('Revenue', definition, intent, {'value': '0', 'data_status': 'value'}) == 'Revenue: 0.'
    assert 'No records matched' in explain_result('Revenue', definition, intent, {'value': None, 'data_status': 'no_matching_rows'})
    assert 'missing' in explain_result('Revenue', definition, intent, {'value': None, 'data_status': 'missing_values'})
    assert 'denominator is zero' in explain_result('Revenue', definition, intent, {'value': None, 'data_status': 'zero_denominator'})
    assert 'Some matching records' in explain_result('Revenue', definition, intent, {'value': '4', 'data_status': 'partial_values'})
    summary = scope_summary(definition, intent)
    assert summary['filter_count'] == 1 and 'USD' not in str(summary)
