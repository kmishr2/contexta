"""Turn approved filter strings into values with catalog-derived SQL types."""
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation


def coerce_filter_value(value: str, column_type: str):
    try:
        if column_type in ('INTEGER', 'BIGINT', 'SMALLINT'):
            number = int(value)
            bounds = {'SMALLINT': (-2**15, 2**15 - 1), 'INTEGER': (-2**31, 2**31 - 1), 'BIGINT': (-2**63, 2**63 - 1)}
            low, high = bounds[column_type]
            if not low <= number <= high:
                raise ValueError('integer out of range')
            return number
        if column_type.startswith(('NUMERIC', 'DECIMAL')):
            number = Decimal(value)
            if not number.is_finite():
                raise ValueError('non-finite numeric value')
            return number
        if column_type == 'BOOLEAN':
            if value.lower() not in ('true', 'false'):
                raise ValueError('boolean value must be true or false')
            return value.lower() == 'true'
        if column_type == 'DATE':
            return date.fromisoformat(value)
        if column_type == 'UUID':
            return uuid.UUID(value)
        return value
    except (ValueError, InvalidOperation, OverflowError) as exc:
        raise ValueError('Filter value does not match the discovered column type') from exc
