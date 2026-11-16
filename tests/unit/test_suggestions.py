from app.onboarding.suggestions import suggest_sources


def test_name_matching_is_scoped_ranked_and_handles_punctuation_and_plurals():
    catalog = {'objects': [{'schema': 'sales', 'name': 'orders'}, {'schema': 'billing', 'name': 'revenue_events'}, {'schema': 'billing', 'name': 'orders'}, {'schema': 'private', 'name': 'customer_data'}]}
    assert [(x['schema'], x['relation']) for x in suggest_sources('How many orders?', catalog)] == [('billing', 'orders'), ('sales', 'orders')]
    assert suggest_sources('Revenue events last month?', catalog)[0]['matched_terms'] == ['event', 'revenue']
    assert suggest_sources('What was it last month?', catalog) == []
    assert all(x['relation'] != 'customer_data' for x in suggest_sources('orders', catalog))
