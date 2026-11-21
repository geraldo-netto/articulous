"""Project validated build state into an implementation-independent publication input."""
import json
from types import MappingProxyType

from .cache_store import cache_payload, finish_cache_update, selected_roots
from .publication_contracts import PublicationBackend, PublicationInput
from .build_contracts import ValidatedBuild
from .builds import _owned_validated
from .composition import route_cache_data
from .output_cache import refresh_output_cache
from .runtime import load_cache


def publication_cache(prepared, routes):
    selected = prepared.cache_selection
    root = str(prepared.destination)
    roots = selected_roots(load_cache(selected.path), root, selected.partitioned)
    cache = dict(prepared.cache)
    cache['__outputs__'] = dict(sorted(prepared.manifest.items()))
    cache['__routes__'] = route_cache_data(routes)
    refresh_output_cache(roots, root, cache, prepared.context.cache_retention_days)
    return json.dumps(cache_payload(selected, roots), indent=2)


def publication_input(checked: ValidatedBuild) -> PublicationInput:
    native = _owned_validated(checked)
    prepared = native._staged._owner
    routes = prepared.manifest.route_values()
    return PublicationInput(
        checked.staged.root, prepared.destination, prepared.cache_path,
        publication_cache(prepared, routes),
        MappingProxyType({path: key for key, path in prepared.manifest.items()}),
        routes,
        checked.assert_unchanged,
    )


def publish_generation(checked: ValidatedBuild, backend: PublicationBackend) -> None:
    native = _owned_validated(checked)
    native.assert_unchanged()
    owner = native._staged._owner
    owner.settle_readers()
    backend.recover(owner.destination, owner.cache_path)
    publication = publication_input(checked)
    backend.publish(publication)
    owner.published(native._revision)
    finish_cache_update(owner.cache_selection, owner.destination, owner.context.cache_retention_days,
                        owner.context.partition_cache)
