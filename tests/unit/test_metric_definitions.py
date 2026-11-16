import pytest
from pydantic import ValidationError
from app.onboarding.metrics import Definition, validate_definition


CATALOG = {'objects': [{'schema': 's', 'name': 't', 'columns': [{'name': 'day', 'type': 'DATE'}, {'name': 'amount', 'type': 'NUMERIC(10, 2)'}, {'name': 'category', 'type': 'TEXT'}]}]}
BASE = {'name': 'Test', 'schema_name': 's', 'relation': 't', 'date_column': 'day'}


def test_aggregate_contract_and_column_types():
    assert validate_definition(Definition(**BASE, aggregate='distinct_count', value_column='category'), CATALOG)
    assert validate_definition(Definition(**BASE, aggregate='ratio', numerator_aggregate='sum', value_column='amount', denominator_aggregate='count'), CATALOG)
    with pytest.raises(ValueError):
        validate_definition(Definition(**BASE, aggregate='avg', value_column='category'), CATALOG)
    with pytest.raises(ValidationError):
        Definition(**BASE, aggregate='count', value_column='amount')
    with pytest.raises(ValidationError):
        Definition(**BASE, aggregate='ratio', numerator_aggregate='sum', value_column='amount', denominator_aggregate='sum')
    with pytest.raises(ValidationError):
        Definition(**BASE, aggregate='sum', value_column='')
