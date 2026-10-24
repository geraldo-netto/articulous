"""REVIEW-022: transaction storage cannot alias configuration state or sources."""
from copy import deepcopy
from pathlib import Path

import pytest

from articulous.config import DEFAULT_CONFIG, normalize_configuration
from articulous.configuration_contracts import BuildRequest
from articulous.backends.posix import PosixPublicationBackend
from articulous.publication import build_site


@pytest.mark.parametrize('block,key,value', [
    ('build', 'cache_file', '.output.articulous-transaction'),
    ('logging', 'file', '.output.articulous-transaction/journal.json'),
    ('paths', 'content_dir', '.output.articulous-transaction/content'),
    ('paths', 'xsl_dir', '.output.articulous-transaction/xsl'),
])
@pytest.mark.parametrize('existing', [False, True])
def test_review022_reserved_paths_reject_before_effects(tmp_path, block, key, value, existing):
    config = deepcopy(DEFAULT_CONFIG)
    config[block][key] = value
    transaction = tmp_path / '.output.articulous-transaction'
    if existing:
        transaction.mkdir()
        (transaction / 'journal.json').write_bytes(b'keep')
    with pytest.raises(ValueError, match='publication transaction'):
        normalize_configuration(config, BuildRequest(), tmp_path)
    assert not (tmp_path / 'output').exists()
    if existing:
        assert (transaction / 'journal.json').read_bytes() == b'keep'


@pytest.mark.parametrize('operation', ['locked', 'recover'])
def test_review022_direct_backend_rejects_cache_alias(tmp_path, operation):
    backend = PosixPublicationBackend()
    output = tmp_path / 'output'
    cache = tmp_path / '.output.articulous-transaction'
    with pytest.raises(ValueError, match='publication transaction'):
        if operation == 'locked':
            with backend.locked(output, cache):
                pytest.fail('reserved cache admitted')
        else:
            backend.recover(output, cache)
    assert not list(tmp_path.iterdir())


def test_review022_reserved_config_input_and_alias(tmp_path):
    transaction = tmp_path / '.output.articulous-transaction'
    transaction.mkdir()
    (tmp_path / 'alias').symlink_to(transaction, target_is_directory=True)
    for path in (Path('.output.articulous-transaction/config.json'), Path('alias/config.json')):
        with pytest.raises(ValueError, match='publication transaction'):
            normalize_configuration(DEFAULT_CONFIG, BuildRequest(config_path=path), tmp_path)


@pytest.mark.parametrize('name', ['.output.articulous-transaction-cache', 'transaction.json'])
def test_review022_nearby_cache_names_publish_and_recover(site_root, seo_config, name):
    cli, config = seo_config
    config['build']['cache_file'] = name
    build_site(cli, config, site_root)
    before = (site_root / 'output/rss.xml').read_bytes()
    build_site(cli, config, site_root)
    assert (site_root / 'output/rss.xml').read_bytes() == before
    assert (site_root / name).is_file()
