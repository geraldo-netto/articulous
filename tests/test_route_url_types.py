"""REVIEW-028: routes and URL admission share one textual boundary."""
from pathlib import Path
import random

import pytest

from articulous.composition_contracts import Route
from articulous.ownership import _decode_routes
from articulous.sections import validate_base_url


def assert_invalid_url(value):
    with pytest.raises(ValueError, match='string'):
        Route('page:about', 'pages', value, 'about/index.html')
    with pytest.raises(ValueError, match='string'):
        validate_base_url(value)


@pytest.mark.parametrize('value', [None, False, True, 0, 1, 0.0, float('nan'), float('inf'),
                                 [], {}, (), b'', b'/about/', Path('/about/')])
def test_review028_route_rejects_nontext_urls(value):
    assert_invalid_url(value)


@pytest.mark.parametrize('url', ['', '/', '/about/', '/caf%C3%A9/', 'https://example.test/about/',
                               'http://example.test:65535/about/'])
def test_review028_supported_textual_boundaries_remain_valid(url):
    route = Route('page:about', 'pages', url, 'about/index.html')
    validate_base_url(url)
    assert route.url == url


def test_review028_seeded_invalid_values_reject_in_both_adapters():
    randomizer = random.Random(28)
    for _ in range(32):
        integer = randomizer.randrange(-(2**128), 2**128)
        for value in (integer, float(integer), [integer], {'url': integer}):
            assert_invalid_url(value)
            data = {'key': 'page:about', 'section': 'pages', 'url': value, 'output_path': 'about/index.html'}
            with pytest.raises(ValueError, match='route metadata'):
                _decode_routes({'page:about': data}, {'about/index.html': 'page:about'})
