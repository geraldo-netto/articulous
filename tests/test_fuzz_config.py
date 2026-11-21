"""Seeded invalid configuration mutations and valid boundary controls."""
import copy
import json
import random
import string

import pytest

from articulous.config import DEFAULT_CONFIG, load_or_create_config, validate_config


SEEDS = (0xBAD5EED, 2026, 0xC0FFEE)
NUMERIC_FIELDS = (
    (("site", "pagination", "per_page"), 1),
    (("site", "pagination", "rss_items"), 0),
    (("build", "parallelism"), 1),
)
STRING_FIELDS = (
    ("paths", "content_dir"), ("site", "site_name"), ("site", "base_url"),
    ("urls", "article"), ("logging", "level"), ("build", "cache_file"),
)


def _set_field(config, path, value):
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _invalid_mutations(seed):
    rng = random.Random(seed)
    for _ in range(25):
        path, minimum = rng.choice(NUMERIC_FIELDS)
        yield path, minimum - rng.randint(1, 10**12)
        yield path, rng.choice([True, False, None, "1", 1.5, [], {}])
        yield rng.choice(STRING_FIELDS), rng.choice([None, False, 42, [], {}])
        yield (rng.choice(tuple(DEFAULT_CONFIG)),), rng.choice([None, False, [], "object"])
        language = "en" + rng.choice(["/", "\\", "?", "#", " ", "\n", "\x00", "é"])
        yield ("site", "languages"), [language]


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_invalid_config_values_fail_without_rewriting_file(tmp_path, seed):
    path = tmp_path / "config.json"
    for field, value in _invalid_mutations(seed):
        config = copy.deepcopy(DEFAULT_CONFIG)
        _set_field(config, field, value)
        content = json.dumps(config).encode()
        path.write_bytes(content)
        with pytest.raises(ValueError):
            load_or_create_config(path)
        assert path.read_bytes() == content, (seed, field, value)


def _invalid_base_urls(seed):
    rng = random.Random(seed)
    invalid = ["not-a-url", "//example.test/blog", "https:///missing", "ftp://example.test"]
    for _ in range(25):
        label = "".join(rng.choices(string.ascii_lowercase, k=8))
        invalid.extend([
            f"https://{label}.test" + rng.choice(["?", "#", "?q=1", "#top"]),
            f"https://{label}.test:{rng.randint(65536, 2**31)}/",
            f"/{label}/" + rng.choice(["..", ".", "%2e%2e", "%GG", "x\ny"]),
        ])
    return invalid


@pytest.mark.parametrize("seed,base_url", [
    (seed, url) for seed in SEEDS for url in _invalid_base_urls(seed)
])
def test_fuzz_invalid_base_urls_are_rejected_without_native_sitemap(seed, base_url):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["engines"]["sitemap"] = "lxml"
    config["site"]["base_url"] = base_url
    with pytest.raises(ValueError, match="site.base_url"):
        validate_config(config)


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_valid_config_boundaries_remain_accepted(seed):
    rng = random.Random(seed)
    for index in range(30):
        config = copy.deepcopy(DEFAULT_CONFIG)
        for path, minimum in NUMERIC_FIELDS:
            _set_field(config, path, rng.choice([minimum, minimum + 1, 2**63, 10**100]))
        port = rng.choice([1, 65535, rng.randint(1, 65535)])
        config["site"]["base_url"] = rng.choice([
            "", "/", "/blog", "/caf%C3%A9/", f"https://example.test:{port}/blog",
        ])
        language = f"lang-{index}"
        config["site"].update(languages=["en", language], default_language=language)
        before = copy.deepcopy(config)
        validate_config(config)
        assert config == before


@pytest.mark.parametrize("path,minimum", NUMERIC_FIELDS)
def test_numeric_minimum_and_immediate_neighbors(path, minimum):
    config = copy.deepcopy(DEFAULT_CONFIG)
    _set_field(config, path, minimum - 1)
    with pytest.raises(ValueError):
        validate_config(config)
    for value in (minimum, minimum + 1):
        _set_field(config, path, value)
        validate_config(config)


def _output_contents(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_invalid_base_urls_cannot_change_published_site(site_root, run_sitegen, seed):
    run_sitegen([])
    config_path = site_root / "config.json"
    config = json.loads(config_path.read_text())
    output_before = _output_contents(site_root / "output")
    cache_before = (site_root / ".build-cache.json").read_bytes()
    ownership_before = (site_root / ".output.articulous-ownership.json").read_bytes()
    for base_url in random.Random(seed).sample(_invalid_base_urls(seed), 5):
        config["site"]["base_url"] = base_url
        content = json.dumps(config)
        config_path.write_text(content)
        result = run_sitegen(["--only", "articles"], check=False)
        assert result.returncode != 0, (seed, base_url)
        assert b"site.base_url" in result.stderr
        assert config_path.read_text() == content
        assert _output_contents(site_root / "output") == output_before
        assert (site_root / ".build-cache.json").read_bytes() == cache_before
        assert (site_root / ".output.articulous-ownership.json").read_bytes() == ownership_before


def test_review28_46_invalid_utf8_and_nesting_report_config_path(tmp_path):
    import sys
    from articulous.configuration_contracts import ConfigurationError
    path = tmp_path / 'local-site.json'
    rng = random.Random(46)
    depth = max(sys.getrecursionlimit() + 100, 10000)
    cases = [b'[' * depth + b'0' + b']' * depth]
    cases.extend(b'{"site":{"site_name":"' + bytes([rng.randrange(0x80, 0x100)]) + b'"}}' for _ in range(16))
    for raw in cases:
        path.write_bytes(raw)
        with pytest.raises(ConfigurationError) as rejected:
            load_or_create_config(path)
        assert str(path) in str(rejected.value)
        assert path.read_bytes() == raw
    path.write_bytes(b'[' * 64 + b'0' + b']' * 64)
    with pytest.raises(ConfigurationError, match='not a JSON object'):
        load_or_create_config(path)


def test_review28_46_integer_decoder_boundary(tmp_path):
    import sys
    from articulous.configuration_contracts import ConfigurationError
    path = tmp_path / 'numbers.json'
    previous = sys.get_int_max_str_digits()
    limit = sys.int_info.str_digits_check_threshold
    try:
        sys.set_int_max_str_digits(limit)
        for digits in (limit - 1, limit, limit + 1):
            raw = '{"site":{"pagination":{"rss_items":' + '1' * digits + '}}}'
            path.write_text(raw)
            if digits <= limit:
                assert load_or_create_config(path)['site']['pagination']['rss_items'] == int('1' * digits)
            else:
                with pytest.raises(ConfigurationError) as rejected:
                    load_or_create_config(path)
                assert str(path) in str(rejected.value)
                assert path.read_text() == raw
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("key", ["article", "index", "tag", "rss", "sitemap", "search"])
def test_route_segments_match_filesystem_structure(key):
    """AUDIT1121-08: reject components a filesystem would collapse."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    tail = config["urls"][key].lstrip("/")
    rng = random.Random(SEEDS[0])
    for prefix in ("", "/"):
        for segment in ("", ".", "..", ".well-known", "news.v2"):
            parent = "/".join(rng.choices(("news", "feed", "archive"), k=rng.randint(1, 4)))
            config["urls"][key] = f"{prefix}{parent}/{segment}/{tail}"
            if segment in ("", ".", ".."):
                with pytest.raises(ValueError, match="segments"):
                    validate_config(config)
            else:
                validate_config(config)
