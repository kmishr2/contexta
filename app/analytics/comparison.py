"""Explicit two-period comparisons over one approved metric."""
import re
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation, localcontext

from app.analytics.grounding import calendar_period
from app.analytics.intent import QueryIntent


_PATTERN = re.compile(r'compare\s+metric\s+([a-z0-9_-]{1,80})\s+(.+?)\s+(?:with|vs|versus)\s+(.+?)\s*\??', re.IGNORECASE)
_RANGE = re.compile(r'from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', re.IGNORECASE)
_CALENDAR = re.compile(r'(?:\d{4}|q[1-4]\s+\d{4}|(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4})', re.IGNORECASE)


def parse_comparison(message: str, today: date) -> tuple[QueryIntent, QueryIntent] | None:
    """Resolve an explicit, fully matched comparison; first window is baseline."""
    match = _PATTERN.fullmatch(message.strip())
    if not match:
        return None
    metric, *windows = match.groups()
    intents = []
    for window in windows:
        window = window.strip()
        try:
            explicit = _RANGE.fullmatch(window)
            if explicit:
                start, end = map(date.fromisoformat, explicit.groups())
                period = None
            elif _CALENDAR.fullmatch(window):
                resolved = calendar_period(window, today)
                if not resolved:
                    return None
                start, end, period = resolved
            else:
                return None
            intents.append(QueryIntent(metric_id=metric, start=start, end=end, period=period))
        except ValueError:
            return None
    return tuple(intents)


def comparison_change(baseline: dict, current: dict) -> dict:
    """Do not infer changes for missing, partial, non-finite or empty data."""
    if any(item['data_status'] != 'value' or item['value'] is None for item in (baseline, current)):
        return {'difference': None, 'percent_change': None, 'reason': 'incomplete_data'}
    if any(len(item['value']) > 1000 for item in (baseline, current)):
        return {'difference': None, 'percent_change': None, 'reason': 'unrepresentable'}
    try:
        a, b = Decimal(baseline['value']), Decimal(current['value'])
        if not a.is_finite() or not b.is_finite():
            raise InvalidOperation
        with localcontext() as ctx:
            ctx.prec = max(28, len(a.as_tuple().digits), len(b.as_tuple().digits)) + 8
            delta = b - a
            if a == 0:
                return {'difference': str(delta), 'percent_change': None, 'reason': 'zero_baseline'}
            percent = (delta / abs(a)) * 100
            return {'difference': str(delta), 'percent_change': str(percent.quantize(Decimal('0.01'))), 'reason': None}
    except (DecimalException, ValueError, OverflowError):
        return {'difference': None, 'percent_change': None, 'reason': 'unrepresentable'}
