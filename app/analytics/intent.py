"""A deliberately narrow, deterministic interpreter for the local prototype."""
import re
from datetime import date

from pydantic import BaseModel, model_validator


class QueryIntent(BaseModel):
    metric_id: str
    start: date
    end: date

    @model_validator(mode='after')
    def check_dates(self):
        if self.start >= self.end:
            raise ValueError('end must be after start')
        return self


DATE_RANGE = r'from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})'
METRIC = r'metric ([A-Za-z0-9_-]{1,80})'


def interpret(message: str, previous: dict | None, pending_metric: str | None):
    text = message.strip()
    full = re.fullmatch(METRIC + r' ' + DATE_RANGE, text, re.IGNORECASE)
    if full:
        metric, start, end = full.groups()
    elif match := re.fullmatch(METRIC, text, re.IGNORECASE):
        return {'kind': 'clarify', 'metric_id': match.group(1), 'message': 'Provide dates as: from YYYY-MM-DD to YYYY-MM-DD. The end date is exclusive.'}
    elif match := re.fullmatch(DATE_RANGE, text, re.IGNORECASE):
        metric = pending_metric or (previous or {}).get('metric_id')
        if not metric:
            return {'kind': 'clarify', 'message': 'Choose a metric first: metric METRIC_ID.'}
        start, end = match.groups()
    else:
        return {'kind': 'unsupported', 'message': 'Use: metric METRIC_ID from YYYY-MM-DD to YYYY-MM-DD. Breakdowns and relative dates are not supported yet.'}
    try:
        intent = QueryIntent(metric_id=metric, start=start, end=end)
    except ValueError:
        return {'kind': 'clarify', 'metric_id': metric, 'message': 'Provide valid dates with the start before the exclusive end date.'}
    return {'kind': 'query', 'intent': intent}
