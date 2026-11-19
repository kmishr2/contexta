from app.evaluation.benchmark import answer_matches, plan_matches, rows_match


def test_benchmark_scores_values_and_scope_not_sql():
    case = {'metric': 'revenue', 'start': '2025-01-01', 'end': '2025-02-01', 'rows': [[None, '100']]}
    proposal = {'type': 'proposal', 'metric': {'id': 'revenue'}, 'date_scope': {'start': case['start'], 'end_exclusive': case['end']}, 'dimensions': []}
    assert plan_matches(case, proposal)
    assert rows_match([['100.00']], case['rows'], False)
    assert not rows_match([['101']], case['rows'], False)
    assert not rows_match([[None]], case['rows'], False)
    assert not rows_match([['NaN']], case['rows'], False)
    assert rows_match([['North', '1.00'], ['South', '1']], [['North', '1'], ['South', '1']], True)
    assert not rows_match([['South', '1'], ['North', '1']], [['North', '1'], ['South', '1']], True)
    answer = {'metric': {'id': 'revenue'}, 'date_scope': proposal['date_scope'], 'columns': ['value'], 'rows': [['100']], 'data_status': 'partial_values', 'truncated': False}
    assert not answer_matches(case, answer)
    answer['data_status'] = 'value'
    assert answer_matches(case, answer)
    proposal['dimensions'] = ['region']
    assert not plan_matches(case, proposal)


def test_benchmark_refuses_nondisposable_targets():
    import pytest
    from scripts.evaluate import validate_target
    assert validate_target('postgresql+psycopg://user@127.0.0.1:55439/contexta_meta_test').database == 'contexta_meta_test'
    for url in [None, 'not a database url', 'postgresql+psycopg://user@remote:55439/contexta_meta_test', 'postgresql+psycopg://user@127.0.0.1:55439/production', 'postgresql+psycopg://user@127.0.0.1:5432/contexta_meta_test']:
        with pytest.raises(ValueError):
            validate_target(url)
