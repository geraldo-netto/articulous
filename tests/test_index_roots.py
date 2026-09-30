"""ARCH-002: canonical roots, empty languages and validated index options."""
from dataclasses import replace
from pathlib import Path
import random
from typing import Any

import lxml.etree as etree
import pytest

from articulous.config import validate_config
from articulous.models import IndexOptions, build_index_models
from articulous.pipeline import BuildCtx, run_build


def context(**changes):
    return replace(BuildCtx(
        content_dir=Path('content'), xsl_dir=Path('xsl'), output_dir=Path('output'),
        assets_dir=Path('assets'), base_url='https://example.test/blog',
        languages=['en', 'fr'], per_page=2, bare_default_language=('index',),
        url_patterns={'index': '/{lang}/page/{page}/'},
    ), **changes)


@pytest.mark.parametrize('count', [0, 1, 2, 3, 6])
@pytest.mark.parametrize('lang,root', [('en', '/'), ('fr', '/fr/')])
def test_arch002_complete_navigation(count, lang, root):
    pages = list(build_index_models(list(range(count)), lang, context(),
                                   options=IndexOptions('/{lang}/', True)))
    urls = [page.url for page in pages]
    assert urls[0] == 'https://example.test/blog' + root
    assert [a for page in pages for a in page.articles] == list(range(count))
    assert [page.previous_url for page in pages] == [''] + urls[:-1]
    assert [page.next_url for page in pages] == urls[1:] + ['']
    assert all(page.total_pages == max(1, (count + 1) // 2) for page in pages)
    assert all('page/1/' not in str(page.output_path) for page in pages)


def test_arch002_defaults_and_encoded_first_route():
    assert list(build_index_models([], 'en', context())) == []
    numbered = list(build_index_models([1], 'en', context()))
    assert numbered[0].output_path == Path('page/1/index.html')
    page, = build_index_models([], 'fr', context(), options=IndexOptions('/café/{lang}/', True))
    assert page.url == 'https://example.test/blog/caf%C3%A9/fr/'
    assert page.output_path == Path('café/fr/index.html')


@pytest.mark.parametrize('seed', range(32))
def test_arch002_invalid_patterns(seed):
    value: Any = random.Random(seed).choice([
        '', 0, False, [], '/{lang}/{page}/', '/{other}/', '/{lang}/index.html',
        '/{lang}/../', '/{lang}//', 'https://host/{lang}/', '/{lang}/%2e/',
        '/{lang!r}/', '/{lang.x}/', '/{lang[0]}/', '/{lang:>3}/', '/{lang}/?x',
    ])
    with pytest.raises(ValueError):
        IndexOptions(value)


@pytest.mark.parametrize('value', [None, 0, 1, 'yes', [], {}])
def test_arch002_invalid_empty_flag(value):
    with pytest.raises(ValueError, match='boolean'):
        IndexOptions(include_empty=value)


@pytest.mark.parametrize('size', [0, -1, True, None, 1.5])
def test_arch002_invalid_page_size(size):
    with pytest.raises(ValueError, match='per_page'):
        list(build_index_models([], 'en', context(per_page=size)))


def test_arch002_unknown_language_and_invalid_options():
    with pytest.raises(ValueError, match='language'):
        list(build_index_models([], 'de', context()))
    invalid: Any = False
    with pytest.raises(ValueError, match='IndexOptions'):
        list(build_index_models([], 'en', context(), options=invalid))
    page, = build_index_models([1], 'en', context(per_page=10**30))
    assert page.articles == [1]


@pytest.mark.parametrize('pattern', ['/{lang}', '/{lang}//', '/{lang}/./', '/{lang}/{{x}/'])
def test_arch002_invalid_directory_boundaries(pattern):
    with pytest.raises(ValueError):
        IndexOptions(pattern)


def configure(config):
    config['urls']['index_first'] = '/{lang}/'
    config['site']['bare_default_language'] = ['index']
    config['site']['pagination'].update(empty_index=True, per_page=1)
    config['sitemap']['include_listings'] = True


def test_arch002_real_build_prunes_aliases_and_keeps_empty_landing(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    configure(config)
    for path in (site_root / 'content/fr').glob('*.xml'):
        path.unlink()
    validate_config(config)
    run_build(cli, config, site_root)
    output = site_root / 'output'
    assert (output / 'index.html').is_file()
    assert (output / 'fr/index.html').is_file()
    assert (output / 'page/2/index.html').is_file()
    assert not list(output.glob('**/page/1/index.html'))
    urls = etree.parse(str(output / 'sitemap.xml')).xpath('//*[local-name()="loc"]/text()')
    assert config['site']['base_url'] + '/' in urls
    assert config['site']['base_url'] + '/fr/' in urls
    run_build(cli, config, site_root)


@pytest.mark.parametrize('key,value', [('index_first', '/{lang}/a.html'), ('empty_index', 1)])
def test_arch002_config_rejects_invalid_options(seo_config, key, value):
    _, config = seo_config
    target = config['urls'] if key == 'index_first' else config['site']['pagination']
    target[key] = value
    with pytest.raises(ValueError):
        validate_config(config)


def test_arch002_root_collision_preserves_site(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    before = (site_root / 'output/en/articles/first-post/index.html').read_bytes()
    config['urls']['index_first'] = '/{lang}/articles/first-post/'
    with pytest.raises(ValueError, match='Duplicate generated output'):
        run_build(cli, config, site_root)
    assert (site_root / 'output/en/articles/first-post/index.html').read_bytes() == before
