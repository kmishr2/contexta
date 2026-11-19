import pytest
from pydantic import ValidationError
from app.onboarding.metrics import Definition, validate_definition

BASE = {'name': 'Payments', 'schema_name': 'billing', 'relation': 'payments', 'aggregate': 'sum', 'value_column': 'amount', 'date_column': 'day'}
CATALOG = {'objects': [{'schema': 'billing', 'name': 'payments', 'columns': [{'name': 'day', 'type': 'DATE'}, {'name': 'amount', 'type': 'NUMERIC(12, 2)'}, {'name': 'status', 'type': 'TEXT'}, {'name': 'currency', 'type': 'VARCHAR(3)'}, {'name': 'payload', 'type': 'JSONB'}]}]}


def test_filters_validate_shapes_scope_and_legacy():
    filters = [{'column': 'status', 'operator': 'in', 'values': ['captured', 'settled']}, {'column': 'currency', 'operator': 'eq', 'values': ['USD']}]
    definition = Definition(**BASE, fixed_filters=filters, dimensions=['currency'])
    assert validate_definition(definition, CATALOG)
    assert len(definition.effective_filters()) == 2
    legacy = Definition(**BASE, filter_column='status', filter_value='captured')
    assert legacy.effective_filters()[0].values == ['captured']
    old_long = Definition(**BASE, filter_column='status', filter_value='x' * 300)
    assert validate_definition(old_long, CATALOG)
    assert len(old_long.effective_filters()[0].values[0]) == 300
    with pytest.raises(ValidationError):
        Definition(**BASE, filter_column='status', filter_value='captured', fixed_filters=filters)
    with pytest.raises(ValidationError):
        Definition(**BASE, fixed_filters=[{'column': 'status', 'operator': 'eq', 'values': []}])
    with pytest.raises(ValidationError):
        Definition(**BASE, fixed_filters=[{'column': 'status', 'operator': 'is_null', 'values': ['x']}])
    with pytest.raises(ValidationError):
        Definition(**BASE, fixed_filters=[{'column': 'status', 'operator': 'eq', 'values': ['x']}] * 2)
    with pytest.raises(ValidationError):
        Definition(**BASE, dimensions=['currency'], fixed_filters=[{'column': 'currency', 'operator': 'in', 'values': ['USD', 'EUR']}])
    with pytest.raises(ValueError):
        validate_definition(Definition(**BASE, fixed_filters=[{'column': 'secret', 'operator': 'eq', 'values': ['x']}]), CATALOG)
    with pytest.raises(ValueError):
        validate_definition(Definition(**BASE, fixed_filters=[{'column': 'payload', 'operator': 'eq', 'values': ['x']}]), CATALOG)


def test_filter_types_are_validated_using_catalog():
    with pytest.raises(ValueError):
        validate_definition(Definition(**BASE, fixed_filters=[{'column': 'amount', 'operator': 'eq', 'values': ['not-a-number']}]), CATALOG)
    with pytest.raises(ValueError):
        validate_definition(Definition(**BASE, fixed_filters=[{'column': 'amount', 'operator': 'in', 'values': ['NaN']}]), CATALOG)
    assert validate_definition(Definition(**BASE, fixed_filters=[{'column': 'amount', 'operator': 'in', 'values': ['1.5', '2']}]), CATALOG)
