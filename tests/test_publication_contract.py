"""REVIEW-013: independent publication inputs and borrowed validation lifetime."""
from contextlib import contextmanager
import json
import operator
from pathlib import Path
import subprocess
import sys

import pytest

from articulous.builds import prepare_build, render_prepared, validate_generated
from articulous.publication import publish_validated
from articulous.publication_contracts import PublicationCapabilities


def test_review013_contract_import_does_not_load_native_or_build_modules():
    script = '''
import sys, typing
sys.modules['fcntl'] = None
from articulous.publication_contracts import PublicationBackend, PublicationInput
assert typing.get_type_hints(PublicationBackend.publish)['publication'] is PublicationInput
assert 'articulous.builds' not in sys.modules
assert 'articulous.filesystem' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


class IndependentBackend:
    capabilities = PublicationCapabilities('contract-test', True, True, True, True)

    def __init__(self):
        self.active = False
        self.received = []
        self.recovered = []

    @contextmanager
    def locked(self, destination, cache_path):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def recover(self, destination, cache_path):
        assert self.active
        self.recovered.append((destination, cache_path))

    def publish(self, publication):
        assert self.active
        assert not hasattr(publication, 'staged')
        publication.verify()
        cache = json.loads(publication.cache_text)['__output_roots__'][str(publication.destination)]
        assert {value: key for key, value in cache['__outputs__'].items()} == publication.output_owners
        assert all((publication.root / path).is_file() for path in publication.output_owners)
        with pytest.raises(TypeError):
            operator.setitem(publication.output_owners, 'unowned', 'injected')
        self.received.append(publication)


def test_review013_independent_backend_receives_narrow_borrow(site_root, seo_config):
    cli, config = seo_config
    backend = IndependentBackend()
    with prepare_build(cli, config, site_root, backend=backend) as prepared:
        checked = validate_generated(render_prepared(prepared))
        publish_validated(checked, backend=backend)
        assert prepared.state == 'published'
        assert len(backend.received) == 1
        assert backend.received[0].destination == site_root / 'output'
        assert backend.received[0].cache_path == site_root / '.build-cache.json'
    assert not backend.active
    with pytest.raises(ValueError):
        backend.received[0].verify()
    assert len(backend.recovered) == 2
