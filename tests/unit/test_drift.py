from copy import deepcopy
from app.onboarding.drift import source_changed


def test_source_qualification_and_view_dependencies():
    catalog = {'objects': [{'schema': 'a', 'name': 'orders', 'kind': 'table', 'columns': ['id']}, {'schema': 'b', 'name': 'orders', 'kind': 'table', 'columns': ['id']}, {'schema': 'a', 'name': 'view', 'kind': 'view', 'columns': ['id']}]}
    updated = deepcopy(catalog)
    updated['objects'][1]['columns'].append('amount')
    assert not source_changed({'schema_name': 'a', 'relation': 'orders'}, catalog, updated)
    assert source_changed({'schema_name': 'b', 'relation': 'orders'}, catalog, updated)
    assert source_changed({'schema_name': 'a', 'relation': 'view'}, catalog, updated)
    updated['objects'] = [obj for obj in updated['objects'] if obj['schema'] != 'a']
    assert source_changed({'schema_name': 'a', 'relation': 'orders'}, catalog, updated)
