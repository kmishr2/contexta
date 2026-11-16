from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from app.analytics.execute import execute_metric

Aggregate = Literal['count', 'distinct_count', 'sum', 'avg']


class Definition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    schema_name: str
    relation: str
    aggregate: Literal['count', 'distinct_count', 'sum', 'avg', 'ratio']
    value_column: str | None = Field(default=None, min_length=1)
    numerator_aggregate: Aggregate | None = None
    denominator_aggregate: Aggregate | None = None
    denominator_column: str | None = Field(default=None, min_length=1)
    date_column: str
    filter_column: str | None = Field(default=None, min_length=1)
    filter_value: str | None = None
    dimensions: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def validate_aggregate(self):
        if self.aggregate == 'ratio':
            if self.numerator_aggregate is None or self.denominator_aggregate is None:
                raise ValueError('A ratio requires numerator and denominator aggregates')
            pairs = [(self.numerator_aggregate, self.value_column), (self.denominator_aggregate, self.denominator_column)]
        else:
            if self.numerator_aggregate is not None or self.denominator_aggregate is not None or self.denominator_column is not None:
                raise ValueError('Ratio fields apply only to ratios')
            pairs = [(self.aggregate, self.value_column)]
        for kind, col in pairs:
            if (kind == 'count') != (col is None):
                raise ValueError('Count uses no column; other aggregates require a column')
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError('A fixed filter needs both a column and value')
        if 'currency' in self.dimensions and any(kind in ('sum', 'avg') for kind, _ in pairs) and self.filter_column != 'currency':
            raise ValueError('An amount with a currency dimension requires a fixed currency filter')
        return self


class ReferenceCheck(BaseModel):
    start: date
    end: date
    expected: Decimal = Field(allow_inf_nan=False)
    tolerance: Decimal = Field(default=Decimal('0'), ge=0, allow_inf_nan=False)
    provenance: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def valid_window(self):
        if self.start >= self.end:
            raise ValueError('end must be after start')
        return self


def validate_definition(definition, catalog):
    obj = next((o for o in catalog['objects'] if o['schema'] == definition.schema_name and o['name'] == definition.relation), None)
    if not obj:
        raise ValueError('Source relation is not in the current catalog')
    cols = {c['name']: c['type'].upper() for c in obj['columns']}
    if definition.date_column not in cols or cols[definition.date_column] != 'DATE':
        raise ValueError('The date column must be a discovered DATE column')
    if definition.aggregate == 'ratio':
        pairs = [(definition.numerator_aggregate, definition.value_column), (definition.denominator_aggregate, definition.denominator_column)]
    else:
        pairs = [(definition.aggregate, definition.value_column)]
    for kind, col in pairs:
        if col and col not in cols:
            raise ValueError('Aggregate column must be discovered')
        if col and kind in ('sum', 'avg') and not cols[col].startswith(('NUMERIC', 'DECIMAL', 'INTEGER', 'BIGINT', 'SMALLINT', 'REAL', 'DOUBLE PRECISION')):
            raise ValueError('Sum and average require numeric columns')
    if definition.filter_column and definition.filter_column not in cols:
        raise ValueError('Filter column must be discovered')
    if any(d not in cols for d in definition.dimensions) or len(set(definition.dimensions)) != len(definition.dimensions):
        raise ValueError('Dimensions must be distinct discovered columns')
    return obj


def run_check(record, settings, definition, check):
    result = execute_metric(record, settings, definition, check)
    actual = Decimal(result['value']) if result['value'] is not None else None
    return {'start': check.start.isoformat(), 'end': check.end.isoformat(), 'expected': str(check.expected), 'tolerance': str(check.tolerance), 'provenance': check.provenance, 'actual': str(actual) if actual is not None else None, 'data_status': result['data_status'], 'passed': actual is not None and result['data_status'] not in ('missing_values', 'zero_denominator', 'non_finite') and abs(actual - check.expected) <= check.tolerance}
