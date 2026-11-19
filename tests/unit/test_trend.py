from datetime import date

from app.analytics.trend import parse_monthly_trend


def test_monthly_trend_is_bounded_and_uses_whole_months():
    months = parse_monthly_trend('trend metric orders 2024 by month')
    assert len(months) == 12
    assert (months[1].start, months[1].end) == (date(2024, 2, 1), date(2024, 3, 1))
    assert (months[-1].start, months[-1].end) == (date(2024, 12, 1), date(2025, 1, 1))
    crossing = parse_monthly_trend('trend metric orders from 2024-12-01 to 2025-02-01 by month?')
    assert len(crossing) == 2 and crossing[-1].end == date(2025, 2, 1)
    for message in ['trend metric orders from 2024-01-02 to 2024-03-01 by month',
                    'trend metric orders from 2024-01-01 to 2025-02-01 by month',
                    'trend metric orders from 2024-01-01 to 2024-01-01 by month',
                    'trend metric orders 9999 by month',
                    'trend metric orders 2025 by month where region is US',
                    'trend metric orders 2025 by month by region',
                    'trend metric orders 2025 by week']:
        assert parse_monthly_trend(message) is None
