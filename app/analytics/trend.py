"""A bounded monthly series for one published metric."""
import re
from datetime import date

from app.analytics.intent import QueryIntent

MAX_TREND_MONTHS = 12
_PATTERN = re.compile(r'trend\s+metric\s+([a-z0-9_-]{1,80})\s+(?:(\d{4})|from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2}))\s+by\s+month\s*\??', re.IGNORECASE)


def parse_monthly_trend(message: str) -> list[QueryIntent] | None:
    match = _PATTERN.fullmatch(message.strip())
    if not match:
        return None
    metric, year, start_text, end_text = match.groups()
    try:
        if year:
            start, end = date(int(year), 1, 1), date(int(year) + 1, 1, 1)
        else:
            start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        months = (end.year - start.year) * 12 + end.month - start.month
        if start.day != 1 or end.day != 1 or not 1 <= months <= MAX_TREND_MONTHS:
            return None
        windows = []
        cursor = start
        for _ in range(months):
            next_month = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
            windows.append(QueryIntent(metric_id=metric, start=cursor, end=next_month, period='calendar_month'))
            cursor = next_month
        return windows
    except (ValueError, OverflowError):
        return None
