import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / 'data' / 'sources.json'


def load_registry():
    sources = json.loads(REGISTRY.read_text())
    ids, urls = set(), set()
    for source in sources:
        if source['id'] in ids or source['url'] in urls:
            raise ValueError('Duplicate source')
        ids.add(source['id'])
        urls.add(source['url'])
    return sources
