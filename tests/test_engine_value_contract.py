"""API-009: malformed engine names have one configuration-error channel."""
from copy import deepcopy
import json
import random

import pytest

from articulous.config import DEFAULT_CONFIG, load_or_create_config, validate_config
from articulous.engines import make_engine
from articulous.pipeline import run_build
from articulous.sections import SECTION_NAMES
from test_prepared_build import snapshot


@pytest.mark.parametrize('value', [[], {}, None, True, False, 0, -1, 1.5, 'unknown'])
def test_api009_engine_json_types_use_validation_error(value):
    for section in SECTION_NAMES:
        config = deepcopy(DEFAULT_CONFIG)
        config['engines'][section] = value
        before = deepcopy(config)
        with pytest.raises(ValueError, match='engine'):
            validate_config(config)
        assert config == before
    with pytest.raises(ValueError, match='engine'):
        make_engine(value, None)


@pytest.mark.parametrize('name', ['lxml', 'saxonc', 'native'])
def test_api009_valid_engine_and_section_controls(name):
    for section in SECTION_NAMES:
        config = deepcopy(DEFAULT_CONFIG)
        config['engines'][section] = name
        if name == 'native' and section not in ('sitemap', 'search'):
            with pytest.raises(ValueError, match='Native engine'):
                validate_config(config)
        else:
            validate_config(config)
    assert make_engine(name, None).name in ('native', 'lxml')


@pytest.mark.parametrize('seed', [0xA81009, 2026, 99])
def test_api009_seeded_invalid_files_preserve_published_state(site_root, seo_config, seed):
    cli, config = seo_config
    run_build(cli, config, site_root)
    state = snapshot(site_root / 'output')
    cache = (site_root / '.build-cache.json').read_bytes()
    ownership = (site_root / '.output.articulous-ownership.json').read_bytes()
    randomizer = random.Random(seed)
    path = site_root / 'config.json'
    for _ in range(16):
        damaged = deepcopy(DEFAULT_CONFIG)
        damaged['engines'][randomizer.choice(SECTION_NAMES)] = randomizer.choice([[], {}, None, False, 2.5])
        encoded = json.dumps(damaged).encode()
        path.write_bytes(encoded)
        with pytest.raises(ValueError, match='engine'):
            load_or_create_config(path)
        assert path.read_bytes() == encoded
    assert snapshot(site_root / 'output') == state
    assert (site_root / '.build-cache.json').read_bytes() == cache
    assert (site_root / '.output.articulous-ownership.json').read_bytes() == ownership
