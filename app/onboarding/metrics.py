from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import MetaData, Table, Column, func, select, text

from app.sources.postgres.discovery import source_engine


class Definition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    schema_name: str
    relation: str
    aggregate: Literal['count', 'sum']
    value_column: str | None = None
    date_column: str
    filter_column: str | None = None
    filter_value: str | None = None
    dimensions: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def validate_aggregate(self):
        if (self.aggregate == 'sum') != (self.value_column is not None):
            raise ValueError('sum requires a value column; count must not specify one')
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError('A fixed filter needs both a column and value')
        if 'currency' in self.dimensions and self.aggregate == 'sum' and self.filter_column != 'currency':
            raise ValueError('A sum with a currency dimension requires a fixed currency filter')
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
    if definition.value_column and (definition.value_column not in cols or not cols[definition.value_column].startswith(('NUMERIC', 'DECIMAL', 'INTEGER', 'BIGINT', 'SMALLINT', 'REAL', 'DOUBLE PRECISION'))):
        raise ValueError('The value column must be numeric')
    if definition.filter_column and definition.filter_column not in cols:
        raise ValueError('Filter column must be discovered')
    if any(d not in cols for d in definition.dimensions) or len(set(definition.dimensions)) != len(definition.dimensions):
        raise ValueError('Dimensions must be distinct discovered columns')
    return obj


def run_check(record, settings, definition, check):
    cols = [Column(definition.date_column)]
    if definition.value_column:
        cols.append(Column(definition.value_column))
    if definition.filter_column and definition.filter_column not in {definition.date_column, definition.value_column}:
        cols.append(Column(definition.filter_column))
    relation = Table(definition.relation, MetaData(), *cols, schema=definition.schema_name)
    aggregate = func.count() if definition.aggregate == 'count' else func.sum(relation.c[definition.value_column])
    stmt = select(aggregate).select_from(relation).where(relation.c[definition.date_column] >= check.start, relation.c[definition.date_column] < check.end)
    if definition.filter_column:
        stmt = stmt.where(relation.c[definition.filter_column] == definition.filter_value)
    engine = source_engine(record, settings)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text('SET TRANSACTION READ ONLY'))
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                conn.execute(text("SET LOCAL lock_timeout = '1s'"))
                conn.execute(text('SET LOCAL search_path = pg_catalog'))
                result = conn.execute(stmt).scalar_one()
                actual = Decimal(str(result)) if result is not None else None
                return {'start': check.start.isoformat(), 'end': check.end.isoformat(), 'expected': str(check.expected), 'tolerance': str(check.tolerance), 'provenance': check.provenance, 'actual': str(actual) if actual is not None else None, 'passed': actual is not None and abs(actual - check.expected) <= check.tolerance}
    finally:
        engine.dispose()
