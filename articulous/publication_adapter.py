"""Project validated build state into an implementation-independent publication input."""
import json
from types import MappingProxyType

from .publication_contracts import PublicationBackend, PublicationInput
from .build_contracts import ValidatedBuild
from .builds import _owned_validated
from .runtime import load_cache


def publication_cache(prepared):
    roots = load_cache(prepared.cache_path).get('__output_roots__', {})
    roots = dict(roots) if isinstance(roots, dict) else {}
    cache = dict(prepared.cache)
    cache['__outputs__'] = dict(sorted(prepared.manifest.items()))
    cache['__routes__'] = prepared.manifest.route_metadata
    roots[str(prepared.destination)] = cache
    return json.dumps({'__output_roots__': roots}, indent=2)


def publication_input(checked: ValidatedBuild) -> PublicationInput:
    native = _owned_validated(checked)
    prepared = native._staged._owner
    return PublicationInput(
        checked.staged.root, prepared.destination, prepared.cache_path,
        publication_cache(prepared),
        MappingProxyType({path: key for key, path in prepared.manifest.items()}),
        MappingProxyType(prepared.manifest.route_values()),
        checked.assert_unchanged,
    )


def publish_generation(checked: ValidatedBuild, backend: PublicationBackend) -> None:
    native = _owned_validated(checked)
    native.assert_unchanged()
    owner = native._staged._owner
    owner.settle_readers()
    publication = publication_input(checked)
    backend.recover(publication.destination, publication.cache_path)
    backend.publish(publication)
    owner.published(native._revision)
