"""API-008: formatter admission precedes expansion and rejects unsafe syntax."""
from copy import deepcopy
import random

import pytest

from articulous.config import DEFAULT_CONFIG, validate_config
from articulous.sections import SECTION_NAMES, url_key_for_section


class NoFormatting(str):
    def format(self, *args, **kwargs):
        raise AssertionError('Rejected pattern reached formatting')


def test_api008_rejects_large_width_before_any_expansion():
    config = deepcopy(DEFAULT_CONFIG)
    config['urls']['index'] = NoFormatting('/{lang}/page/{page:999999999999}/')
    with pytest.raises(ValueError, match='placeholder'):
        validate_config(config)


@pytest.mark.parametrize('section', SECTION_NAMES)
@pytest.mark.parametrize('seed', [0xA81008, 2026, 0xBAD])
def test_api008_seeded_invalid_placeholder_grammar(section, seed):
    randomizer = random.Random(seed)
    field, pattern = api008_pattern(section)
    changes = [field + '.__class__', field + '[0]', field + '!s', field + '!r',
               field + ':1000000', field + ':{page}', field + ':>1000000']
    for changed in randomizer.sample(changes, len(changes)):
        config = deepcopy(DEFAULT_CONFIG)
        config['urls'][url_key_for_section(section)] = pattern.replace('{' + field + '}', '{' + changed + '}')
        before = deepcopy(config)
        with pytest.raises(ValueError, match='placeholder'):
            validate_config(config)
        assert config == before


def api008_pattern(section):
    field = {'articles': 'slug', 'index': 'page', 'tags': 'tag', 'rss': 'lang'}.get(section, 'unexpected')
    pattern = DEFAULT_CONFIG['urls'][url_key_for_section(section)]
    if section == 'rss':
        pattern = '/{lang}/rss.xml'
    if section in ('sitemap', 'search'):
        pattern = '/{' + field + '}' + pattern
    return field, pattern


@pytest.mark.parametrize('section', ['articles', 'index', 'tags', 'rss'])
@pytest.mark.parametrize('bare', [False, True])
def test_api008_plain_placeholders_preserve_valid_bare_routes(section, bare):
    _, pattern = api008_pattern(section)
    config = deepcopy(DEFAULT_CONFIG)
    config['urls'][url_key_for_section(section)] = '/café' + pattern
    config['site']['bare_default_language'] = [section] if bare else []
    validate_config(config)
