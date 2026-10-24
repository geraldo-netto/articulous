"""API-010: independent request/schema admission and non-CLI consumers."""
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
import subprocess
import sys

import pytest

from articulous import config
from articulous.builds import check_build
from articulous.pipeline import run_build


def test_api010_contract_import_excludes_implementations():
    script = '''
import sys
sys.modules['articulous.engines'] = None
sys.modules['articulous.cli'] = None
sys.modules['fcntl'] = None
from articulous.configuration_contracts import BuildRequest, SiteConfiguration, ConfigurationError
assert BuildRequest().only_sections is None
assert SiteConfiguration.__required_keys__ == {
    'paths', 'engines', 'saxonc', 'sitemap', 'robots', 'site', 'urls', 'build', 'logging'}
assert 'articulous.config' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_api010_schema_does_not_follow_implementation_defaults(monkeypatch):
    value = deepcopy(config.DEFAULT_CONFIG)
    monkeypatch.setitem(config.DEFAULT_CONFIG['paths'], 'implementation_only', 'unused')
    config.validate_config(value)


def test_api010_non_cli_request_drives_both_build_apis(site_root):
    from articulous.configuration_contracts import BuildRequest
    request = BuildRequest()
    assert check_build(request, {}, site_root).routes > 0
    assert not (site_root / 'output').exists()
    run_build(request, {}, site_root)
    assert (site_root / 'output/rss.xml').is_file()


@pytest.mark.parametrize('field,value', [
    ('dry_run', 1), ('verbose', None), ('force_full_build', 'true'),
    ('only_sections', 'rss'), ('only_sections', ['unknown']),
    ('only_langs', [False]), ('only_slugs', ['']), ('config_path', None),
    ('only_langs', 42),
])
def test_api010_request_invalid_values(field, value):
    from articulous.configuration_contracts import BuildRequest, ConfigurationError
    with pytest.raises(ConfigurationError):
        BuildRequest(**{field: value})


def test_api010_request_copies_selection_borrows():
    from articulous.configuration_contracts import BuildRequest
    sections = ['rss', 'rss']
    request = BuildRequest(only_sections=sections, config_path=Path('alternate.json'))
    sections.append('articles')
    assert request.only_sections == ('rss',)
    assert request.config_path == Path('alternate.json')


@pytest.mark.parametrize('value', [None, [], {'unknown': 'lxml'}, {None: 'native'}])
def test_api010_engine_schema_rejects_invalid_mappings(value):
    from articulous.configuration_contracts import ConfigurationError, validate_engines
    with pytest.raises(ConfigurationError):
        validate_engines(value)


@pytest.mark.parametrize('value', [None, [], 42])
def test_api010_direct_schema_admission_rejects_non_mappings(value):
    from articulous.configuration_contracts import ConfigurationError
    with pytest.raises(ConfigurationError, match='Configuration'):
        config.admit_configuration(value)


def test_api010_readonly_configuration_input_is_captured(site_root):
    from articulous.configuration_contracts import BuildRequest
    original = {'site': {'site_name': 'Independent'}}
    supplied = MappingProxyType(original)
    normalized = config.normalize_configuration(supplied, BuildRequest(only_sections=[]), site_root)
    assert normalized['site']['site_name'] == 'Independent'
    assert normalized['paths']['output_dir'] == str(site_root / 'output')
    normalized['site']['site_name'] = 'Owned copy'
    assert original == {'site': {'site_name': 'Independent'}}


@pytest.mark.parametrize('value', [None, [], {'paths': None}, {'engines': {'articles': []}}])
def test_api010_normalization_errors_leave_inputs_and_output_untouched(site_root, value):
    from articulous.configuration_contracts import BuildRequest, ConfigurationError
    before = deepcopy(value)
    with pytest.raises(ConfigurationError):
        check_build(BuildRequest(), value, site_root)
    assert value == before
    assert not (site_root / 'output').exists()
