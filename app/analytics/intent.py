"""A deliberately narrow, deterministic interpreter for the local prototype."""
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


class QueryIntent(BaseModel):
    metric_id: str
    start: date
    end: date
    period: str | None = None
    reporting_timezone: str | None = None
    dimensions: list[str] = Field(default_factory=list, max_length=1)

    @model_validator(mode='after')
    def check_dates(self):
        if self.start >= self.end:
            raise ValueError('end must be after start')
        return self


DATE_RANGE = r'from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})'
METRIC = r'metric ([A-Za-z0-9_-]{1,80})'


def reporting_today(zone: str) -> date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(zone)).date()


def last_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1)
    start = date(end.year - 1, 12, 1) if end.month == 1 else date(end.year, end.month - 1, 1)
    return start, end


def interpret(message: str, previous: dict | None, pending_metric: str | None, *, metrics: list[dict] | None = None, today: date | None = None, reporting_timezone: str = 'UTC'):
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
        question = re.fullmatch(r'(?:what (?:was|is) )(.+?) last month\??', text, re.IGNORECASE)
        followup = re.fullmatch(r'(?:and )?last month\??', text, re.IGNORECASE)
        if not question and not followup:
            return {'kind': 'unsupported', 'message': 'Try: What was METRIC NAME last month? Or: metric METRIC_ID from YYYY-MM-DD to YYYY-MM-DD. Breakdowns are not supported yet.'}
        if question:
            name = question.group(1).strip().casefold()
            candidates = [m for m in (metrics or []) if name in {m['id'].casefold(), m['name'].strip().casefold()}]
            if len(candidates) > 1:
                return {'kind': 'clarify', 'message': 'More than one published metric matches that name. Use its metric ID and an explicit date range.'}
            if not candidates:
                return {'kind': 'unsupported', 'message': 'No published metric matches that name in this connection.'}
            metric = candidates[0]['id']
        else:
            metric = pending_metric or (previous or {}).get('metric_id')
            if not metric:
                return {'kind': 'clarify', 'message': 'Choose a metric first: metric METRIC_ID.'}
        start, end = last_month(today or reporting_today(reporting_timezone))
        return {'kind': 'query', 'intent': QueryIntent(metric_id=metric, start=start, end=end, period='last_calendar_month', reporting_timezone=reporting_timezone)}
    try:
        intent = QueryIntent(metric_id=metric, start=start, end=end)
    except ValueError:
        return {'kind': 'clarify', 'metric_id': metric, 'message': 'Provide valid dates with the start before the exclusive end date.'}
    return {'kind': 'query', 'intent': intent}
