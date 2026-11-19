"""Compile only owner-approved aggregates against one qualified source."""
from sqlalchemy import Column, MetaData, Numeric, Table, cast, func, select
from app.analytics.filter_values import coerce_filter_value


def build_metric_query(definition, start, end, dimensions=None, limit=None):
    dimensions = dimensions or []
    names = {definition.date_column, *dimensions}
    names.update(name for name in (definition.value_column, definition.denominator_column) if name)
    names.update(item.column for item in definition.effective_filters())
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
    for item in definition.effective_filters():
        # Types come from the reviewed catalog, never from model output.
        column_type = definition._filter_types.get(item.column)
        if column_type is None:
            raise ValueError('Filter types must be resolved against the catalog')
        values = [coerce_filter_value(value, column_type) for value in item.values]
        col = relation.c[item.column]
        if item.operator == 'eq':
            stmt = stmt.where(col == values[0])
        elif item.operator == 'in':
            stmt = stmt.where(col.in_(values))
        elif item.operator == 'is_null':
            stmt = stmt.where(col.is_(None))
        else:
            stmt = stmt.where(col.is_not(None))
    if dimensions:
        dim = relation.c[dimensions[0]]
        stmt = stmt.add_columns(dim).group_by(dim).order_by(dim.asc().nulls_last()).limit((limit or 100) + 1)
    return stmt
