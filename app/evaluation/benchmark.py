"""Fixed benchmark expectations, independent of the SQL compiler."""
from datetime import date
from decimal import Decimal, InvalidOperation

from app.llm.contracts import ChatPlan


CASES = [
    {'id': 'commerce_january', 'connection': 'commerce', 'chat': 'commerce_revenue', 'question': 'What was recognized USD revenue from 2025-01-01 to 2025-02-01? The end date is exclusive.', 'expected': 'answer', 'metric': 'recognized', 'start': '2025-01-01', 'end': '2025-02-01', 'rows': [[None, '100']]},
    {'id': 'commerce_followup', 'connection': 'commerce', 'chat': 'commerce_revenue', 'question': 'And from 2025-02-01 to 2025-03-01? The end date is exclusive.', 'expected': 'answer', 'metric': 'recognized', 'start': '2025-02-01', 'end': '2025-03-01', 'rows': [[None, '-20']]},
    {'id': 'subscriptions_revenue', 'connection': 'subscriptions', 'chat': 'sub_revenue', 'question': 'What was recognized USD revenue from 2025-01-01 to 2025-02-01? The end date is exclusive.', 'expected': 'answer', 'metric': 'recognized', 'start': '2025-01-01', 'end': '2025-02-01', 'rows': [[None, '120']]},
    {'id': 'subscriptions_members', 'connection': 'subscriptions', 'chat': 'members', 'question': 'How many live members joined from 2025-01-01 to 2025-02-01? The end date is exclusive.', 'expected': 'answer', 'metric': 'active_members', 'start': '2025-01-01', 'end': '2025-02-01', 'rows': [[None, '2']]},
    {'id': 'subscriptions_breakdown', 'connection': 'subscriptions', 'chat': 'members', 'question': 'Break that down by market.', 'expected': 'answer', 'metric': 'active_members', 'start': '2025-01-01', 'end': '2025-02-01', 'dimension': 'market', 'rows': [['North', '1'], ['South', '1']]},
    {'id': 'unavailable_breakdown', 'connection': 'commerce', 'chat': 'commerce_revenue', 'question': 'Break revenue down by product.', 'expected': 'decline'},
    {'id': 'unknown_metric', 'connection': 'subscriptions', 'chat': 'unknown', 'question': 'What was product churn from 2025-01-01 to 2025-02-01?', 'expected': 'decline'},
]


def rows_match(actual, expected, grouped):
    if len(actual) != len(expected):
        return False
    try:
        for row, (group, value) in zip(actual, expected):
            if grouped:
                if len(row) != 2 or row[0] != group:
                    return False
                actual_value = row[1]
            else:
                if len(row) != 1:
                    return False
                actual_value = row[0]
            if actual_value is None or not Decimal(str(actual_value)).is_finite() or Decimal(str(actual_value)) != Decimal(value):
                return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    return True


def plan_matches(case, response):
    scope = response.get('date_scope', {})
    return (response.get('type') == 'proposal' and response.get('metric', {}).get('id') == case['metric']
            and scope.get('start') == case['start'] and scope.get('end_exclusive') == case['end']
            and response.get('dimensions', []) == ([case['dimension']] if case.get('dimension') else []))



def answer_matches(case, data):
    dimension = case.get('dimension')
    if data.get('truncated') or data.get('metric', {}).get('id') != case['metric']:
        return False
    scope = data.get('date_scope', {})
    if scope.get('start') != case['start'] or scope.get('end_exclusive') != case['end']:
        return False
    if data.get('columns') != ([dimension, 'value'] if dimension else ['value']):
        return False
    if dimension:
        statuses = data.get('row_statuses', [])
        if len(statuses) != len(case['rows']) or any(status != 'value' for status in statuses):
            return False
    elif data.get('data_status') != 'value':
        return False
    return rows_match(data.get('rows', []), case['rows'], bool(dimension))


def fake_plan(system, payload, response_model):
    """Fixture fake: benchmark questions map to plans, never SQL."""
    candidates = [c for c in CASES if c['question'] == payload['question']]
    available = {m['id'] for m in payload['metrics']}
    candidates = [c for c in candidates if c.get('metric') in available or c['expected'] == 'decline']
    if not candidates:
        return ChatPlan(kind='unsupported', message='No fixture plan')
    case = candidates[0]
    if case['expected'] == 'decline':
        return ChatPlan(kind='unsupported', message='Not available')
    previous = payload.get('previous_intent')
    if case['id'] in ('commerce_followup', 'subscriptions_breakdown'):
        if not previous or previous.get('metric_id') != case['metric']:
            return ChatPlan(kind='clarify', message='Please choose a metric first')
    return ChatPlan(kind='query', message='Review', metric_id=case['metric'], period='explicit',
                    start=date.fromisoformat(case['start']), end=date.fromisoformat(case['end']),
                    dimensions=[case['dimension']] if case.get('dimension') else [])
