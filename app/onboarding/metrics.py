import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from app.analytics.execute import execute_metric
from app.analytics.filter_values import coerce_filter_value

Aggregate = Literal['count', 'distinct_count', 'sum', 'avg']


class FixedFilter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    column: str = Field(min_length=1, max_length=128)
    operator: Literal['eq', 'in', 'is_null', 'is_not_null']
    values: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def validate_values(self):
        if any(len(value) > 256 for value in self.values):
            raise ValueError('Filter values must be at most 256 characters')
        if self.operator == 'eq' and len(self.values) != 1:
            raise ValueError('Equality requires exactly one value')
        if self.operator == 'in' and not self.values:
            raise ValueError('In requires at least one value')
        if self.operator in ('is_null', 'is_not_null') and self.values:
            raise ValueError('Null checks cannot contain values')
        if len(set(self.values)) != len(self.values):
            raise ValueError('Filter values must be distinct')
        return self


class Definition(BaseModel):
    _filter_types: dict[str, str] = PrivateAttr(default_factory=dict)
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
    fixed_filters: list[FixedFilter] = Field(default_factory=list, max_length=10)
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
        if self.filter_column and self.fixed_filters:
            raise ValueError('Use either legacy filter fields or fixed_filters, not both')
        columns = [item.column for item in self.fixed_filters]
        if len(columns) != len(set(columns)):
            raise ValueError('Each fixed filter must use a distinct column')
        currency_fixed = self.filter_column == 'currency' or any(item.column == 'currency' and item.operator in ('eq', 'in') and len(item.values) == 1 for item in self.fixed_filters)
        if 'currency' in self.dimensions and any(kind in ('sum', 'avg') for kind, _ in pairs) and not currency_fixed:
            raise ValueError('An amount with a currency dimension requires a fixed currency filter')
        return self

    def effective_filters(self) -> list[FixedFilter]:
        if self.filter_column is not None:
            # Older persisted definitions may contain long values; keep them readable.
            return [FixedFilter.model_construct(column=self.filter_column, operator='eq', values=[self.filter_value])]
        return self.fixed_filters


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
    definition._filter_types = {}
    for item in definition.effective_filters():
        if item.column not in cols:
            raise ValueError('Filter column must be discovered')
        if item.operator in ('eq', 'in'):
            supported = r'(?:VARCHAR(?:\(\d+\))?|CHAR(?:\(\d+\))?|TEXT|INTEGER|BIGINT|SMALLINT|NUMERIC(?:\(\d+(?:,\s*\d+)?\))?|DECIMAL(?:\(\d+(?:,\s*\d+)?\))?|BOOLEAN|DATE|UUID)'
            if not re.fullmatch(supported, cols[item.column]):
                raise ValueError('Filter type is not supported for equality or membership')
            for value in item.values:
                coerce_filter_value(value, cols[item.column])
        definition._filter_types[item.column] = cols[item.column]
    if any(d not in cols for d in definition.dimensions) or len(set(definition.dimensions)) != len(definition.dimensions):
        raise ValueError('Dimensions must be distinct discovered columns')
    return obj


def run_check(record, settings, definition, check):
    result = execute_metric(record, settings, definition, check)
    actual = Decimal(result['value']) if result['value'] is not None else None
    return {'start': check.start.isoformat(), 'end': check.end.isoformat(), 'expected': str(check.expected), 'tolerance': str(check.tolerance), 'provenance': check.provenance, 'actual': str(actual) if actual is not None else None, 'data_status': result['data_status'], 'passed': actual is not None and result['data_status'] not in ('missing_values', 'zero_denominator', 'non_finite') and abs(actual - check.expected) <= check.tolerance}
