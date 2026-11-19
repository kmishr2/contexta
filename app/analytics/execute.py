import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from app.analytics.compiler import build_metric_query
from app.sources.postgres.discovery import source_engine

MAX_ROWS = 100
MAX_BYTES = 256 * 1024


class ResultTooLarge(Exception):
    pass


def normalize_dimension(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def execute_metric(record, settings, definition, intent):
    return execute_metrics(record, settings, definition, [intent])[0]


def execute_metrics(record, settings, definition, intents):
    """Execute related queries against one repeatable, read-only snapshot."""
    engine = source_engine(record, settings)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                conn.execute(text("SET LOCAL lock_timeout = '1s'"))
                conn.execute(text('SET LOCAL search_path = pg_catalog'))
                results = []
                for intent in intents:
                    dimensions = getattr(intent, 'dimensions', []) or []
                    stmt = build_metric_query(definition, intent.start, intent.end, dimensions, MAX_ROWS)
                    cursor = conn.execute(stmt)
                    rows = cursor.fetchmany(MAX_ROWS + 1) if dimensions else [cursor.one()]
                    truncated = len(rows) > MAX_ROWS
                    output = []
                    for row in rows[:MAX_ROWS]:
                        value, matched, populated = row[:3]
                        denominator, denominator_count = row[3:5] if definition.aggregate == 'ratio' else (None, None)
                        if matched == 0:
                            status = 'no_matching_rows'
                        elif populated == 0 or (denominator_count is not None and denominator_count == 0):
                            status = 'missing_values'
                        elif definition.aggregate == 'ratio' and denominator == 0:
                            status = 'zero_denominator'
                        elif populated < matched or (denominator_count is not None and denominator_count < matched):
                            status = 'partial_values'
                        else:
                            status = 'value'
                        if value is not None:
                            try:
                                if not Decimal(str(value)).is_finite():
                                    value, status = None, 'non_finite'
                            except InvalidOperation:
                                value, status = None, 'non_finite'
                        item = {'value': str(value) if value is not None else None, 'data_status': status}
                        if dimensions:
                            item['dimension'] = normalize_dimension(row[-1])
                        output.append(item)
                        if len(json.dumps(output, ensure_ascii=True).encode('utf-8')) > MAX_BYTES:
                            raise ResultTooLarge('Result exceeds byte limit')
                    sql = str(stmt.compile(dialect=conn.dialect))
                    if dimensions:
                        results.append({'groups': output, 'truncated': truncated, 'sql': sql})
                    else:
                        results.append({**output[0], 'sql': sql})
                return results
    finally:
        engine.dispose()
