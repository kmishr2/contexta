"""Compare a metric's reviewed source with a refreshed catalog."""


def source_changed(definition: dict, reviewed: dict, current: dict) -> bool:
    def find(catalog):
        return next((obj for obj in catalog.get('objects', []) if obj.get('schema') == definition.get('schema_name') and obj.get('name') == definition.get('relation')), None)

    before, after = find(reviewed), find(current)
    if before is None or after is None:
        return True
    # Views can depend on other catalog objects and grants. Until those dependencies
    # are captured, conservatively treat any catalog change as affecting a view.
    if before.get('kind') == 'view' or after.get('kind') == 'view':
        return reviewed != current
    return before != after
