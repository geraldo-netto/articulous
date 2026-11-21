"""Project validated build state into an implementation-independent publication input."""
from contextlib import closing
import json
from types import MappingProxyType
from uuid import uuid4

from .cache_activity import CacheActivity
from .cache_store import cache_payload, finish_cache_update, selected_roots
from .publication_contracts import PublicationBackend, PublicationInput, StagedPublicationInput, uses_staged_publication
from .filesystem import private_directory
from .ownership import ownership_payload
from .publication_json import ObjectMembers, stage_json
from .build_contracts import ValidatedBuild
from .builds import _owned_validated
from .output_cache import refresh_output_cache
from .runtime import load_cache
from .translations import translation_history


def _cache_payload(prepared, generation, activity):
    selected = prepared.cache_selection
    root = str(prepared.destination)
    roots = selected_roots(load_cache(selected.path), root, selected.partitioned)
    cache = dict(prepared.cache)
    cache['__generation__'] = generation
    refresh_output_cache(roots, root, cache, prepared.context.cache_retention_days, activity)
    return cache_payload(selected, roots)


def publication_input(checked: ValidatedBuild, activity: CacheActivity) -> PublicationInput:
    native = _owned_validated(checked)
    prepared = native._staged._owner
    routes = prepared.manifest.route_values()
    generation = uuid4().hex
    return PublicationInput(
        checked.staged.root, prepared.destination, prepared.cache_path,
        json.dumps(_cache_payload(prepared, generation, activity), indent=2),
        MappingProxyType({path: key for key, path in prepared.manifest.items()}),
        routes,
        checked.assert_unchanged, generation,
        MappingProxyType(dict(translation_history(prepared.cache, prepared.manifest))),
    )


def _ordered_translations(prepared):
    with closing(prepared.routes.output_paths()) as rows:
        yield from translation_history(prepared.cache, (key for key, _ in rows))


def _stage_publication(checked, prepared, directory, activity):
    catalog = prepared.routes
    generation = uuid4().hex
    cache = _cache_payload(prepared, generation, activity)
    cache_file = stage_json(directory / 'cache.json', cache)
    translations = ObjectMembers(_ordered_translations(prepared))
    owners = ownership_payload(prepared.destination, ObjectMembers(catalog.output_paths(inverse=True)),
                               ObjectMembers(catalog.serialized_routes()), generation=generation,
                               translations=translations)
    ownership_file = stage_json(directory / 'ownership.json', owners, sorted_keys=True)
    return StagedPublicationInput(checked.staged.root, prepared.destination, prepared.cache_path,
                                  cache_file, ownership_file, checked.assert_unchanged)


def publish_generation(checked: ValidatedBuild, backend: PublicationBackend) -> None:
    native = _owned_validated(checked)
    native.assert_unchanged()
    _publish_current(native, backend)


def _publish_current(checked, backend):
    native = _owned_validated(checked)
    native.require_current()
    owner = native._staged._owner
    owner.settle_readers()
    backend.recover(owner.destination, owner.cache_path)
    activity = CacheActivity(owner.cache_path, owner.cache_selection.base)
    publish = backend.publish
    if uses_staged_publication(publish):
        with private_directory(checked.staged.root.parent) as directory:
            source = _stage_publication(checked, owner, directory, activity)
            activity.prepare_retirement()
            publish(source)
    else:
        source = publication_input(checked, activity)
        activity.prepare_retirement()
        publish(source)
    owner.published(native._revision)
    finish_cache_update(owner.cache_selection, owner.context.cache_retention_days,
                        owner.context.partition_cache)
