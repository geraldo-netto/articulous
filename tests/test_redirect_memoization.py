"""PERF-19: share suffixes while preserving link-specific redirect diagnostics."""
from random import Random
from urllib.parse import urlsplit
from unittest.mock import patch

import pytest

from articulous import site_validation as validation


BASE = 'https://example.test'


def assert_result(output, memo, mapping, route, fragment):
    initial = BASE + route + fragment
    target = output / route.strip('/') / 'index.html'
    expected_errors, errors = [], []
    expected_path, expected_url = validation.redirect_target(
        output, target, initial, BASE, mapping, expected_errors, route,
    )
    path, url = memo.follow(target, initial, errors, route)
    assert errors == expected_errors
    assert path == expected_path
    if path is not None:
        assert urlsplit(url) == urlsplit(expected_url)


@pytest.mark.parametrize('seed', range(8))
def test_perf19_suffixes_match_existing_graph_walk(tmp_path, seed):
    random = Random(seed)
    routes = [f'/{index}/' for index in range(12)]
    endings = ['', '?v=2', '#', '#new', '#a%20b']
    redirects = {route: random.choice(routes + ['/terminal/', '@other.test/']) + random.choice(endings)
                 for route in routes}
    redirects.update({'/cycle/': '/cycle-two/#other', '/cycle-two/': '/cycle/',
                      '/loop-entry/': '/cycle-two/', '/first/': '/next/#', '/next/': '/done/?x=y'})
    memo = validation._RedirectResolver(tmp_path, BASE, redirects, {})
    for route in [*redirects, '/unaltered/']:
        for fragment in ('', '#incoming', '#incoming%20space'):
            assert_result(tmp_path, memo, redirects, route, fragment)


def test_perf19_evaluates_shared_suffix_one_time(tmp_path):
    redirects = {f'/{index}/': f'/{index+1}/' for index in range(64)}
    memo = validation._RedirectResolver(tmp_path, BASE, redirects, {})
    target = tmp_path / '0/index.html'
    with patch.object(validation, 'resolved_path', wraps=validation.resolved_path) as resolver:
        for index in range(128):
            final, url = memo.follow(target, BASE + f'/0/#x{index}', [], str(index))
            assert final == tmp_path / '64/index.html'
            assert url == BASE + f'/64/#x{index}'
    assert resolver.call_count == 64
