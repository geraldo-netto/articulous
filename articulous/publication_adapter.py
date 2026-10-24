"""Project validated build state into an implementation-independent publication input."""
import json
from types import MappingProxyType

from .publication_contracts import PublicationInput
from .runtime import load_cache


def publication_cache(prepared):
    roots = load_cache(prepared.cache_path).get('__output_roots__', {})
    roots = dict(roots) if isinstance(roots, dict) else {}
    cache = dict(prepared.cache)
    cache['__outputs__'] = dict(sorted(prepared.manifest.items()))
    cache['__routes__'] = prepared.manifest.route_metadata
    roots[str(prepared.destination)] = cache
    return json.dumps({'__output_roots__': roots}, indent=2)


def publication_input(checked) -> PublicationInput:
    prepared = checked.staged.prepared
    return PublicationInput(
        checked.staged.root, prepared.destination, prepared.cache_path,
        publication_cache(prepared),
        MappingProxyType({path: key for key, path in prepared.manifest.items()}),
        MappingProxyType(prepared.manifest.route_values()),
        checked.assert_unchanged,
    )
