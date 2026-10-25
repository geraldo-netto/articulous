"""REVIEW-023: executed with isolated installed Python outside the checkout."""
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sys

import articulous
from articulous.theme_resources import code_resources, prism_provenance, search_resources
from articulous.tooling_resources import tooling_resources


def require_installed_inventory(root, expected):
    actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
    assert actual == expected


def require_provenance(root):
    manifest = prism_provenance()
    for name, digest in manifest['files'].items():
        assert hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() == digest
    assert root.joinpath(manifest['patch']).read_text().startswith('--- prismjs-1.30.0/')
    for name in ('code-blocks', 'search-client'):
        assert root.joinpath('contracts/' + name + '.d.ts').read_bytes()


def main():
    package = Path(articulous.__file__).resolve().parent
    assert package.is_relative_to(Path(sys.prefix).resolve())
    require_installed_inventory(package, json.loads(Path(sys.argv[1]).read_text()))
    require_provenance(files('articulous').joinpath('theme_assets'))
    resources = [tuple(tooling_resources()), tuple(code_resources()), tuple(search_resources())]
    assert all(resource.content for group in resources for resource in group)
    print(json.dumps(dict(package=str(package), tooling=len(resources[0]),
                          code=len(resources[1]), search=len(resources[2]))))


if __name__ == '__main__':
    main()
