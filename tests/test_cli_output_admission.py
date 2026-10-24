"""REVIEW-014: CLI and API reject original output symlinks before writes."""
import json

import pytest

from articulous.config import load_or_create_config, normalize_configuration
from articulous.configuration_contracts import BuildRequest
from articulous.ownership import ownership_path


@pytest.mark.parametrize('ancestor', [False, True])
def test_review014_cli_and_api_preserve_symlink_destination(site_root, run_sitegen, ancestor):
    config_path = site_root / 'config.json'
    config = json.loads(config_path.read_text())
    target = site_root / 'actual'
    target.mkdir()
    (target / 'manual.txt').write_bytes(b'keep')
    alias = site_root / 'alias'
    alias.symlink_to(target, target_is_directory=True)
    config['paths']['output_dir'] = 'alias/generated' if ancestor else 'alias'
    config_path.write_text(json.dumps(config))
    admitted = load_or_create_config(config_path)
    with pytest.raises(ValueError, match='symlink'):
        normalize_configuration(admitted, BuildRequest(), site_root)
    result = run_sitegen(['--only', 'rss'], check=False)
    assert result.returncode != 0
    assert b'symlink' in result.stderr
    assert (target / 'manual.txt').read_bytes() == b'keep'
    assert not (target / 'rss.xml').exists()
    assert not (target / 'generated').exists()
    assert not (site_root / '.build-cache.json').exists()
    assert not ownership_path(target).exists()


def test_review014_cli_rejects_empty_symlink_before_publication(site_root, run_sitegen):
    target = site_root / 'actual'
    target.mkdir()
    (site_root / 'output').symlink_to(target, target_is_directory=True)
    result = run_sitegen(['--only', 'rss'], check=False)
    assert result.returncode != 0
    assert b'symlink' in result.stderr
    assert not list(target.iterdir())
