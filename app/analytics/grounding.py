"""Conservative checks against local-model substitutions."""
import re
from datetime import date, timedelta
from app.onboarding.suggestions import terms

GENERIC = {'total', 'count', 'number', 'amount', 'value', 'rate', 'metric', 'usd', 'eur', 'gbp'}


def metric_is_grounded(question: str, metric_id: str, metric_name: str, previous: dict | None, dimensions: list[str]) -> bool:
    words = {w for w in terms(question) if not w.isdigit()} - GENERIC
    metric_words = (terms(metric_id) | terms(metric_name)) - GENERIC
    if words & metric_words:
        return True
    if not previous or previous.get('metric_id') != metric_id:
        return False
    # Only recognize unambiguous date-only or exact-dimension follow-ups. Other
    # expressions require clarification rather than guessing a prior metric.
    if re.fullmatch(r'(?:and\s+)?(?:for\s+)?from\s+\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}\??(?:\s+the\s+end\s+date\s+is\s+exclusive\.)?', question.strip(), re.IGNORECASE):
        return True
    if len(dimensions) == 1:
        dimension = re.escape(dimensions[0])
        if re.fullmatch(r'(?:and\s+)?(?:(?:break\s+that\s+down|breakdown)\s+)?(?:by|per)\s+' + dimension + r'[?.]?', question.strip(), re.IGNORECASE):
            return True
    return bool(re.fullmatch(r'(?:and\s+)?last\s+month\??', question.strip(), re.IGNORECASE))


def verified_breakdown_followup(question: str, previous: dict | None, available: list[dict]):
    """Resolve only an exact dimension follow-up against the last accepted intent."""
    if not previous:
        return None
    match = re.fullmatch(r'(?:and\s+)?(?:(?:break\s+that\s+down|breakdown)\s+)?(?:by|per)\s+(.+?)[?.]?', question.strip(), re.IGNORECASE)
    if not match:
        return None
    metric = next((item for item in available if item['id'] == previous.get('metric_id')), None)
    if metric is None:
        return None
    candidates = [name for name in metric['dimensions'] if name.casefold() == match.group(1).strip().casefold()]
    if len(candidates) != 1:
        return None
    return {'metric_id': metric['id'], 'dimension': candidates[0], 'start': previous.get('start'), 'end': previous.get('end')}


def supported_clarification_answer(text: str, metrics: list[dict]) -> bool:
    """Allow narrow date or metric replies; other constraints must be restated."""
    value = text.strip().rstrip('?').strip()
    if any(value.casefold() in {item['id'].casefold(), item['name'].strip().casefold()} for item in metrics):
        return True
    if re.fullmatch(r'(?:last\s+(?:month|week|quarter|year)|\d{4}|q[1-4]\s+\d{4}|(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4})', value, re.IGNORECASE):
        return True
    return bool(re.fullmatch(r'(?:from\s+)?\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}(?:\s+exclusive)?', value, re.IGNORECASE))


MONTHS = {'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3, 'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9, 'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12}


def calendar_period(text: str, today: date) -> tuple[date, date, str] | None:
    """Resolve exactly one supported calendar expression into a half-open window."""
    relative = list(re.finditer(r'\blast\s+(week|month|quarter|year)\b', text, re.IGNORECASE))
    months = list(re.finditer(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{4})\b', text, re.IGNORECASE))
    quarters = list(re.finditer(r'\bq([1-4])\s+(\d{4})\b', text, re.IGNORECASE))
    # Exclude year components already consumed by a month, quarter or ISO date.
    occupied = [m.span() for m in months + quarters] + [m.span() for m in re.finditer(r'\b\d{4}-\d{2}-\d{2}\b', text)]
    years = [m for m in re.finditer(r'\b\d{4}\b', text) if not any(a <= m.start() < b for a, b in occupied)]
    if len(relative) + len(months) + len(quarters) + len(years) != 1 or re.search(r'\b\d{4}-\d{2}-\d{2}\b', text):
        return None
    try:
        if relative:
            unit = relative[0].group(1).lower()
            if unit == 'week':
                end = today - timedelta(days=today.weekday())
                return end - timedelta(days=7), end, 'last_calendar_week'
            if unit == 'month':
                end = today.replace(day=1)
                start = date(end.year - 1, 12, 1) if end.month == 1 else date(end.year, end.month - 1, 1)
            elif unit == 'quarter':
                end = date(today.year, 1 + 3 * ((today.month - 1) // 3), 1)
                start = date(end.year - 1, 10, 1) if end.month == 1 else date(end.year, end.month - 3, 1)
            else:
                end = date(today.year, 1, 1)
                start = date(today.year - 1, 1, 1)
            return start, end, 'last_calendar_' + unit
        if months:
            year, month = int(months[0].group(2)), MONTHS[months[0].group(1).lower()]
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            return start, end, 'calendar_month'
        if quarters:
            year, month = int(quarters[0].group(2)), 1 + (int(quarters[0].group(1)) - 1) * 3
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 10 else date(year, month + 3, 1)
            return start, end, 'calendar_quarter'
        year = int(years[0].group())
        return date(year, 1, 1), date(year + 1, 1, 1), 'calendar_year'
    except (ValueError, OverflowError):
        return None


def period_is_grounded(text: str, plan, exact_followup: bool = False, previous: dict | None = None, today: date | None = None) -> bool:
    """Reject a model-invented period; date arithmetic remains application-controlled."""
    if exact_followup and previous:
        return plan.period == 'explicit' and str(plan.start) == previous.get('start') and str(plan.end) == previous.get('end')
    # Comparisons require two query windows and are not supported by a
    # single-period plan, even if the model silently drops one side.
    if re.search(r'\b(?:compare|compared|comparison|versus|vs|against)\b|\b(?:this|next|previous)\s+(?:week|month|quarter|year)\b', text, re.IGNORECASE):
        return False
    if plan.period == 'last_month':
        resolved = calendar_period(text, today or date.today())
        return bool(resolved and resolved[2] == 'last_calendar_month')
    if plan.period != 'explicit':
        return False
    explicit_dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
    if len(explicit_dates) == 2:
        remainder = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text)
        if re.search(r'\b\d{4}\b|\blast\s+(?:week|month|quarter|year)\b', remainder, re.IGNORECASE):
            return False
        return explicit_dates == [str(plan.start), str(plan.end)]
    resolved = calendar_period(text, today or date.today())
    if resolved:
        return (plan.start, plan.end) == resolved[:2]
    return False
