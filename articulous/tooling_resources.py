"""Optional native-testing resources; callers own any materialized files."""
from importlib.resources import files
from .resource_contracts import ResourceFile


def tooling_resources():
    root = files('articulous').joinpath('tooling_assets')
    return tuple(ResourceFile(name, root.joinpath(name).read_bytes())
                 for name in ('browser-session.mjs', 'native-coverage.mjs', 'javascript-syntax.mjs'))
