from sqlalchemy import Column, MetaData, Table, func, select, text
from app.sources.postgres.discovery import source_engine


def execute_metric(record, settings, definition, intent):
    names = {definition.date_column}
    if definition.value_column:
        names.add(definition.value_column)
    if definition.filter_column:
        names.add(definition.filter_column)
    relation = Table(definition.relation, MetaData(), *(Column(n) for n in sorted(names)), schema=definition.schema_name)
    aggregate = func.count() if definition.aggregate == 'count' else func.sum(relation.c[definition.value_column])
    value_count = func.count(relation.c[definition.value_column]) if definition.value_column else func.count()
    stmt = select(aggregate, func.count(), value_count).select_from(relation).where(relation.c[definition.date_column] >= intent.start, relation.c[definition.date_column] < intent.end)
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
                value, matched, populated = conn.execute(stmt).one()
                status = 'no_matching_rows' if matched == 0 else ('missing_values' if definition.value_column and populated == 0 else 'value')
                return {'value': str(value) if value is not None else None, 'data_status': status,
                        'sql': str(stmt.compile(dialect=conn.dialect))}
    finally:
        engine.dispose()
