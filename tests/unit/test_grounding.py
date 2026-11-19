from app.analytics.grounding import metric_is_grounded


def test_metric_grounding_fails_closed_and_allows_clear_followups():
    previous = {'metric_id': 'recognized'}
    assert metric_is_grounded('What was recognized USD revenue?', 'recognized', 'Recognized USD revenue', None, [])
    assert not metric_is_grounded('What was product churn?', 'recognized', 'Recognized USD revenue', None, [])
    assert not metric_is_grounded('And what was product churn?', 'recognized', 'Recognized USD revenue', previous, [])
    assert metric_is_grounded('And from 2025-02-01 to 2025-03-01? The end date is exclusive.', 'recognized', 'Recognized USD revenue', previous, [])
    assert metric_is_grounded('Break that down by market.', 'recognized', 'Recognized USD revenue', previous, ['market'])
    assert not metric_is_grounded('Break that down by product.', 'recognized', 'Recognized USD revenue', previous, ['market'])


def test_exact_breakdown_followup_keeps_prior_scope_and_rejects_extra_filters():
    from app.analytics.grounding import verified_breakdown_followup
    previous = {'metric_id': 'active', 'start': '2025-01-01', 'end': '2025-02-01'}
    metrics = [{'id': 'active', 'dimensions': ['market']}]
    assert verified_breakdown_followup('Break that down by market.', previous, metrics) == {'metric_id': 'active', 'dimension': 'market', 'start': '2025-01-01', 'end': '2025-02-01'}
    assert verified_breakdown_followup('And by MARKET?', previous, metrics)['dimension'] == 'market'
    assert verified_breakdown_followup('Break that down by market where status is active', previous, metrics) is None
    assert verified_breakdown_followup('Break that down by region', previous, metrics) is None
    assert verified_breakdown_followup('Break that down by market', None, metrics) is None


def test_clarification_answers_cannot_silently_add_filters():
    from app.analytics.grounding import supported_clarification_answer
    metrics = [{'id': 'sales', 'name': 'Sales revenue'}]
    assert supported_clarification_answer('January 2025', metrics)
    assert supported_clarification_answer('sales revenue', metrics)
    assert supported_clarification_answer('from 2025-01-01 to 2025-02-01', metrics)
    assert not supported_clarification_answer('January 2025 but only in Europe', metrics)
    assert not supported_clarification_answer('yes, exclude refunds', metrics)


def test_period_grounding_rejects_invented_dates():
    from datetime import date
    from app.analytics.grounding import period_is_grounded
    from app.llm.contracts import ChatPlan
    plan = ChatPlan(kind='query', message='review', metric_id='orders', period='explicit', start=date(2025, 1, 1), end=date(2025, 2, 1))
    assert not period_is_grounded('How many orders?', plan)
    assert period_is_grounded('How many orders in January 2025?', plan)
    assert period_is_grounded('Orders from 2025-01-01 to 2025-02-01', plan)
    assert not period_is_grounded('Orders from 2025-01-01 to 2025-01-31', plan)
    assert not period_is_grounded('Orders from 2025-01-01 to 2025-02-01 versus 2024', plan)
    assert not period_is_grounded('Orders in January 2025 and last year', plan)
    assert not period_is_grounded('Orders in January 2025 and this year', plan)
    prior = {'start': '2025-01-01', 'end': '2025-02-01'}
    assert period_is_grounded('and by region?', plan, exact_followup=True, previous=prior)
    relative = ChatPlan(kind='query', message='review', metric_id='orders', period='last_month')
    assert period_is_grounded('orders last month', relative)
    assert not period_is_grounded('orders this year', relative)


def test_calendar_periods_and_boundaries():
    from datetime import date
    from app.analytics.grounding import calendar_period, supported_clarification_answer
    today = date(2025, 1, 1)  # Wednesday; previous week crossed the year.
    assert calendar_period('orders last week', today) == (date(2024, 12, 23), date(2024, 12, 30), 'last_calendar_week')
    assert calendar_period('orders last quarter', today) == (date(2024, 10, 1), date(2025, 1, 1), 'last_calendar_quarter')
    assert calendar_period('orders last year', today) == (date(2024, 1, 1), date(2025, 1, 1), 'last_calendar_year')
    assert calendar_period('orders Q1 2024', today) == (date(2024, 1, 1), date(2024, 4, 1), 'calendar_quarter')
    assert calendar_period('orders in 2024', today) == (date(2024, 1, 1), date(2025, 1, 1), 'calendar_year')
    assert calendar_period('orders in February 2024', today) == (date(2024, 2, 1), date(2024, 3, 1), 'calendar_month')
    assert calendar_period('orders in 9999', today) is None
    assert calendar_period('orders Q1 2024 versus Q2 2024', today) is None
    assert calendar_period('orders last month in 2024', today) is None
    assert supported_clarification_answer('Q1 2024', [])
    assert supported_clarification_answer('last quarter', [])
