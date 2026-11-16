"""Compile only owner-approved aggregates against one qualified source."""
from sqlalchemy import Column, MetaData, Numeric, Table, cast, func, select


def build_metric_query(definition, start, end, dimensions=None, limit=None):
    dimensions = dimensions or []
    names = {definition.date_column, *dimensions}
    names.update(name for name in (definition.value_column, definition.denominator_column, definition.filter_column) if name)
    relation = Table(definition.relation, MetaData(), *(Column(name) for name in sorted(names)), schema=definition.schema_name)

    def aggregate(kind, name):
        col = relation.c[name] if name else None
        if kind == 'count':
            return func.count(), func.count()
        if kind == 'distinct_count':
            return func.count(func.distinct(col)), func.count(col)
        if kind == 'sum':
            return func.sum(col), func.count(col)
        if kind == 'avg':
            return func.avg(col), func.count(col)
        raise ValueError('Unsupported aggregate')

    kind = definition.numerator_aggregate if definition.aggregate == 'ratio' else definition.aggregate
    numerator, numerator_count = aggregate(kind, definition.value_column)
    if definition.aggregate == 'ratio':
        denominator, denominator_count = aggregate(definition.denominator_aggregate, definition.denominator_column)
        value = cast(numerator, Numeric) / func.nullif(cast(denominator, Numeric), 0)
    else:
        denominator, denominator_count, value = None, None, numerator
    parts = [value, func.count(), numerator_count]
    if denominator is not None:
        parts.extend([denominator, denominator_count])
    stmt = select(*parts).select_from(relation).where(relation.c[definition.date_column] >= start, relation.c[definition.date_column] < end)
    if definition.filter_column:
        stmt = stmt.where(relation.c[definition.filter_column] == definition.filter_value)
    if dimensions:
        dim = relation.c[dimensions[0]]
        stmt = stmt.add_columns(dim).group_by(dim).order_by(dim.asc().nulls_last()).limit((limit or 100) + 1)
    return stmt
