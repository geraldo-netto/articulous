"""A failed cache save must not make stale fingerprints authoritative."""
import pytest

from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
from articulous.ownership import load_ownership
from articulous.pipeline import run_build


def _configuration(root):
    cli = CliOptions(parse_cli_args([]))
    config = load_or_create_config(root / "config.json")
    apply_cli_overrides(config, cli, root)
    return cli, config


@pytest.mark.parametrize("source,before,after", [
    ("content/en/first-post.xml", b"Inaugural article.", b"Interim content."),
    ("xsl/pages/article.xsl", b"description", b"title"),
])
def test_failed_cache_save_rebuilds_reverted_inputs(site_root, monkeypatch, source, before, after):
    cli, config = _configuration(site_root)
    run_build(cli, config, site_root)
    changed = site_root / source
    original_source = changed.read_bytes()
    page = site_root / "output/en/articles/first-post/index.html"
    original_page = page.read_bytes()
    changed.write_bytes(original_source.replace(before, after))
    with monkeypatch.context() as patch:
        patch.setattr("articulous.runtime.write_text_atomic", _fail_cache_write)
        run_build(cli, config, site_root)
    assert load_ownership(site_root / "output").pending
    assert page.read_bytes() != original_page
    changed.write_bytes(original_source)
    run_build(cli, config, site_root)
    assert page.read_bytes() == original_page
    assert not load_ownership(site_root / "output").pending


def _fail_cache_write(*_args):
    raise OSError("cache write failed")


def test_failed_cache_save_requires_full_recovery(site_root, monkeypatch):
    cli, config = _configuration(site_root)
    with monkeypatch.context() as patch:
        patch.setattr("articulous.runtime.write_text_atomic", _fail_cache_write)
        run_build(cli, config, site_root)
    cli.only_sections = ["articles"]
    with pytest.raises(ValueError, match="full recovery"):
        run_build(cli, config, site_root)
