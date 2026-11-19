"""Deterministic, result-grounded explanations for approved queries."""


def explain_result(metric_name: str, definition, intent, execution: dict) -> str:
    if intent.dimensions:
        groups = execution['groups']
        if not groups:
            return f'No matching records were found for {metric_name} in the selected period.'
        text = f'{metric_name} is shown for {len(groups)} {intent.dimensions[0]} group' + ('' if len(groups) == 1 else 's') + '.'
        if execution['truncated']:
            text += ' More groups exist; only the first 100 are shown.'
        if any(row['data_status'] != 'value' for row in groups):
            text += ' Some groups have missing values or an undefined calculation; see their status.'
        return text
    status = execution['data_status']
    if status == 'no_matching_rows':
        return f'No records matched {metric_name} in the selected period.'
    if status == 'missing_values':
        return f'{metric_name} could not be calculated because the required values are missing.'
    if status == 'zero_denominator':
        return f'{metric_name} is undefined because its denominator is zero.'
    if status == 'non_finite':
        return f'{metric_name} could not be displayed because the result is not finite.'
    result = f"{metric_name}: {execution['value']}."
    if status == 'partial_values':
        result += ' Some matching records have missing values.'
    return result


def scope_summary(definition, intent) -> dict:
    filters = definition.effective_filters()
    # Do not put filter names or values in the public explanation; owners can
    # inspect the full definition separately, while analysts have limited visibility.
    return {'start': intent.start.isoformat(), 'end_exclusive': intent.end.isoformat(),
            'reporting_timezone': intent.reporting_timezone, 'period': intent.period,
            'dimensions': intent.dimensions,
            'filter_count': len(filters),
            'filter_note': 'Owner-approved filters apply.' if filters else 'No fixed filters apply.'}
