"""Deterministic catalog matching; all proposed sources require owner review."""
import re

STOP_WORDS = frozenset({'a', 'an', 'and', 'are', 'by', 'did', 'do', 'for', 'from', 'how', 'i', 'in', 'is', 'last', 'many', 'me', 'month', 'of', 'on', 'our', 'show', 'the', 'to', 'was', 'we', 'what', 'were', 'with'})


def terms(value: str) -> set[str]:
    words = re.findall(r'[^\W_]+', value.casefold())
    return {word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith('ss') else word for word in words if word not in STOP_WORDS}


def suggest_sources(message: str, catalog: dict) -> list[dict]:
    query = terms(message)
    matches = []
    for obj in catalog['objects']:
        matched = sorted(query & terms(obj['name']))
        if matched:
            matches.append({'schema': obj['schema'], 'relation': obj['name'], 'matched_terms': matched})
    matches.sort(key=lambda x: (-len(x['matched_terms']), x['schema'], x['relation']))
    return matches[:10]
