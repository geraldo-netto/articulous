"""Seeded boundary probes preserve output and cache when limits are exceeded."""
import copy
from dataclasses import replace
import os
import random

import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.filesystem import validate_path_length
from articulous.pipeline import build_ctx_from_config, build_sitemap_section
from articulous.sections import validate_sitemap_location


SEEDS = (0xB0A, 2026, 0xC0FFEE)


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_sitemap_url_length_boundary(seed):
    rng = random.Random(seed)
    lengths = list(range(2043, 2054))
    rng.shuffle(lengths)
    for length in lengths:
        prefix = f"https://example.test:{rng.randint(1, 65535)}/"
        url = prefix + "x" * (length - len(prefix))
        assert len(url) == length
        if length < 2048:
            validate_sitemap_location(url)
        else:
            with pytest.raises(ValueError, match="2048"):
                validate_sitemap_location(url)


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_port_boundaries(seed):
    rng = random.Random(seed)
    invalid = [-1, 0, 65536] + [rng.randint(65537, 10**30) for _ in range(20)]
    for port in invalid:
        with pytest.raises(ValueError):
            validate_sitemap_location(f"https://example.test:{port}/")
    for port in [1, 65535] + [rng.randint(1, 65535) for _ in range(20)]:
        validate_sitemap_location(f"https://example.test:{port}/")


def _native_context(site_root):
    config = load_or_create_config(site_root / "config.json")
    cli = CliOptions(parse_cli_args([]))
    apply_cli_overrides(config, cli, site_root)
    return replace(build_ctx_from_config(config, False), force=True)


def _publish_sitemap(ctx, cache, urls):
    tasks = build_sitemap_section(urls, ctx, cache)
    assert len(tasks) == 1
    tasks[0]()
    return (ctx.output_dir / "sitemap.xml").read_bytes()


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_sitemap_count_limit_preserves_prior_publication(site_root, monkeypatch, seed):
    rng = random.Random(seed)
    ctx = _native_context(site_root)
    cache = {}
    for _ in range(5):
        limit = rng.randint(2, 20)
        monkeypatch.setattr("articulous.pipeline._SITEMAP_MAX_URLS", limit)
        urls = [f"https://example.test/page-{index}/" for index in range(limit)]
        before = _publish_sitemap(ctx, cache, urls)
        previous_cache = copy.deepcopy(cache)
        with pytest.raises(ValueError, match="50,000 URL"):
            _publish_sitemap(ctx, cache, [*urls, "https://example.test/extra/"])
        assert (ctx.output_dir / "sitemap.xml").read_bytes() == before
        assert cache == previous_cache
        assert list(ctx.output_dir.glob(".articulous-*")) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_sitemap_byte_limit_and_neighbors(site_root, monkeypatch, seed):
    rng = random.Random(seed)
    ctx = _native_context(site_root)
    cache = {}
    for _ in range(5):
        # Scaled byte budgets must stay above the fixed XML envelope.
        urls = [f"https://example.test/{rng.getrandbits(32)}/" for _ in range(rng.randint(1, 8))]
        before = _publish_sitemap(ctx, cache, urls)
        previous_cache = copy.deepcopy(cache)
        with monkeypatch.context() as patch:
            patch.setattr("articulous.pipeline._SITEMAP_MAX_BYTES", len(before) - 1)
            with pytest.raises(ValueError, match="50 MiB"):
                _publish_sitemap(ctx, cache, urls)
            assert (ctx.output_dir / "sitemap.xml").read_bytes() == before
            assert cache == previous_cache
            for limit in (len(before), len(before) + 1):
                patch.setattr("articulous.pipeline._SITEMAP_MAX_BYTES", limit)
                assert _publish_sitemap(ctx, cache, urls) == before


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_filesystem_component_byte_limit(tmp_path, seed):
    rng = random.Random(seed)
    limit = os.pathconf(tmp_path, "PC_NAME_MAX")
    if limit < 1:
        pytest.skip("Filesystem reports no component length limit")
    sizes = list(range(limit - 3, limit + 5))
    rng.shuffle(sizes)
    for size in sizes:
        character = rng.choice(["a", "é", "界"])
        width = len(character.encode())
        name = character * (size // width) + "x" * (size % width)
        assert len(name.encode()) == size
        if size <= limit:
            validate_path_length(tmp_path / name)
        else:
            with pytest.raises(ValueError, match="filesystem limit"):
                validate_path_length(tmp_path / name)
    assert list(tmp_path.iterdir()) == []
