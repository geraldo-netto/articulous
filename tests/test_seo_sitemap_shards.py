"""SEO-08: shard publication is bounded, deterministic and recoverable."""
import json
import tracemalloc
from itertools import repeat

import lxml.etree as etree
import pytest

import articulous.pipeline as pipeline
import articulous.sitemaps as sitemaps
from articulous.filesystem import TempWorkspace


def _shard_files(root):
    tree = etree.parse(str(root / "output/sitemap.xml"))
    urls = tree.xpath("/*[local-name()='sitemapindex']/*/*[local-name()='loc']/text()")
    return [root / "output" / url.rsplit("/", 1)[-1] for url in urls]


def test_seo08_count_shards_are_deterministic_and_shrinking_prunes(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    monkeypatch.setattr(pipeline, "_SITEMAP_MAX_URLS", 2)
    pipeline.run_build(cli, config, site_root)
    shards = _shard_files(site_root)
    assert len(shards) == 2
    counts = [len(etree.parse(str(path)).getroot()) for path in shards]
    assert counts == [2, 1]
    before = {path: path.stat().st_mtime_ns for path in shards}
    pipeline.run_build(cli, config, site_root)
    assert _shard_files(site_root) == shards
    assert before == {path: path.stat().st_mtime_ns for path in shards}
    (site_root / "content/fr/premier.xml").unlink()
    pipeline.run_build(cli, config, site_root)
    assert not _shard_files(site_root)
    assert all(not path.exists() for path in shards)
    assert len(etree.parse(str(site_root / "output/sitemap.xml")).getroot()) == 2


def test_seo08_failed_shard_keeps_old_index_and_recovers(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    monkeypatch.setattr(pipeline, "_SITEMAP_MAX_URLS", 1)
    pipeline.run_build(cli, config, site_root)
    index = site_root / "output/sitemap.xml"
    before = index.read_bytes()
    old_shards = {path: path.read_bytes() for path in _shard_files(site_root)}
    source = site_root / "content/en/first-post.xml"
    source.write_text(source.read_text().replace("</article>", "<modified>2025-01-01</modified></article>"))
    original = pipeline._write_native_sitemap
    calls = []

    def fail_shard(output, values):
        calls.append(output)
        original(output, values)
        raise OSError("interrupted shard publication")

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_write_native_sitemap", fail_shard)
        with pytest.raises(OSError, match="interrupted shard"):
            pipeline.run_build(cli, config, site_root)
    assert calls
    assert index.read_bytes() == before
    assert old_shards == {path: path.read_bytes() for path in old_shards}
    assert json.loads((site_root / ".output.articulous-ownership.json").read_text())["pending"]
    pipeline.run_build(cli, config, site_root)
    assert index.read_bytes() != before
    assert not json.loads((site_root / ".output.articulous-ownership.json").read_text())["pending"]


def test_seo08_dry_run_does_not_publish_shards(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    cli.dry_run = True
    monkeypatch.setattr(pipeline, "_SITEMAP_MAX_URLS", 1)
    pipeline.run_build(cli, config, site_root)
    assert not (site_root / "output").exists()


@pytest.mark.parametrize("count,expected", [(50_000, [50_000]), (50_001, [50_000, 1])])
def test_seo08_exact_count_boundaries_use_bounded_memory(count, expected):
    with TempWorkspace() as workspace:
        tracemalloc.start()
        try:
            shards = sitemaps.partition_sitemap(workspace, repeat("https://example.test/a/", count), 50_000, sitemaps.MAX_BYTES)
            assert [sum(1 for _ in shard.values()) for shard in shards] == expected
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert peak < 2_000_000


@pytest.mark.parametrize("delta,expected", [(-1, [1, 1]), (0, [2]), (1, [2])])
def test_seo08_utf8_byte_boundaries(tmp_path, delta, expected):
    url = "https://example.test/é/"
    output = tmp_path / "sample.xml"
    pipeline._write_native_sitemap(output, [url, url])
    budget = output.stat().st_size + delta
    with TempWorkspace() as workspace:
        shards = sitemaps.partition_sitemap(workspace, [url, url], 50_000, budget)
        assert [sum(1 for _ in shard.values()) for shard in shards] == expected


def test_seo08_unshardable_entry_and_empty_envelope_limits(tmp_path):
    output = tmp_path / "empty.xml"
    pipeline._write_native_sitemap(output, [])
    envelope = output.stat().st_size
    with TempWorkspace() as workspace:
        shards = sitemaps.partition_sitemap(workspace, [], 50_000, envelope)
        assert list(shards[0].values()) == []
        with pytest.raises(ValueError, match="envelope"):
            sitemaps.partition_sitemap(workspace, [], 50_000, envelope - 1)
        with pytest.raises(ValueError, match="entry"):
            sitemaps.partition_sitemap(workspace, ["https://example.test/a/"], 50_000, envelope)
    with pytest.raises(ValueError, match="50 MiB"):
        sitemaps.write_document(output, [], "urlset", sitemaps.native_entry, 50_000, envelope - 1)


@pytest.mark.parametrize("kind", ["truncated", "changed"])
def test_seo08_corrupt_spool_is_rejected(kind):
    with TempWorkspace() as workspace:
        shard = sitemaps.partition_sitemap(workspace, ["https://example.test/a/"], 50_000, sitemaps.MAX_BYTES)[0]
        content = b"" if kind == "truncated" else shard.path.read_bytes().replace(b"/a/", b"/b/")
        shard.path.write_bytes(content)
        with pytest.raises(ValueError, match="Sitemap spool"):
            list(shard.values())


@pytest.mark.parametrize("limit", ["MAX_URLS", "MAX_BYTES"])
def test_seo08_index_limits_are_enforced(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(sitemaps, limit, 1)
    with pytest.raises(ValueError, match="50,000 URL|50 MiB"):
        sitemaps.write_index(tmp_path / "index.xml", ["https://example.test/a.xml", "https://example.test/b.xml"])
