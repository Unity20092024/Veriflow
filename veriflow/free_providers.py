"""Explicit allowlist: only these reviewed free adapters can auto-run."""
SOURCES={'lib-reviews':('online_discovery','online_collection'),
         'mangrove-reviews':('mangrove_discovery','mangrove_collection')}
MODES={mode:source for source,modes in SOURCES.items() for mode in modes}


def adapter(source_id):
    if source_id=='lib-reviews':
        from . import free_collection
        return free_collection
    if source_id=='mangrove-reviews':
        from . import mangrove_collection
        return mangrove_collection
    from .connectors import AccessDenied
    raise AccessDenied('Provider is not in the reviewed free allowlist')


def mode_for(source_id,kind):
    adapter(source_id)
    return SOURCES[source_id][0 if kind=='catalog' else 1]
