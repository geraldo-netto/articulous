"""LIFE-001: retained child iterators cannot outlive captured-source ownership."""
from articulous.builds import prepare_build
from articulous.extensions import BuildComposition
from articulous.builds import capture_site
import pytest


class RetainedReader:
    def __init__(self, source):
        self.source = iter(source)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.source)

    def close(self):
        self.source.close()
        self.closed = True


class RetainedBatch:
    def __init__(self, batch, children, reader=RetainedReader):
        self.batch, self.children, self.reader = batch, children, reader

    def __iter__(self):
        child = self.reader(self.batch)
        self.children.append(child)
        return child


def test_life001_snapshot_closes_every_retained_child_reader(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    children = []
    snapshots = []
    readers = []
    def compose(snapshot):
        snapshots.append(snapshot)
        original = snapshot._store.sorted
        def retained(language):
            return RetainedBatch(original(language), children)
        monkeypatch.setattr(snapshot._store, 'sorted', retained)
        readers.append(snapshot.articles())
        next(readers[0])
        return BuildComposition()
    with prepare_build(cli, config, site_root, composer=compose):
        snapshots[0].close()
        assert children
        assert all(child.closed for child in children)
    readers[0].close()


def test_life001_child_close_failure_still_settles_all_spools(site_root, seo_config, monkeypatch):
    import pytest
    cli, config = seo_config
    failures = []
    children = []
    snapshots = []
    readers = []
    class FaultyReader(RetainedReader):
        def close(self):
            super().close()
            if failures:
                raise OSError('child close failed after settlement')
    def compose(snapshot):
        snapshots.append(snapshot)
        original = snapshot._store.sorted
        def retained(language):
            return RetainedBatch(original(language), children, FaultyReader)
        monkeypatch.setattr(snapshot._store, 'sorted', retained)
        readers.append(snapshot.articles())
        next(readers[0])
        return BuildComposition()
    with prepare_build(cli, config, site_root, composer=compose):
        failures.append(True)
        with pytest.raises(OSError, match='child close failed'):
            snapshots[0].close()
        assert all(child.closed for child in children)
        assert all(source.closed for source in snapshots[0]._store._files.values())
        assert snapshots[0]._store._sources.closed
    readers[0].close()


def retained_storage(snapshot):
    paths = snapshot._store._workspace._paths
    return len(paths), sum(path.stat().st_size for path in paths)


def test_review011_repeated_reads_reuse_sorted_spools(site_root, seo_config):
    cli, config = seo_config
    with capture_site(cli, config, site_root) as snapshot:
        assert retained_storage(snapshot)[0] == 3
        expected = list(snapshot.articles())
        first = retained_storage(snapshot)
        assert first[0] == 5
        for _ in range(9):
            assert list(snapshot.articles()) == expected
            assert retained_storage(snapshot) == first
        paths = list(snapshot._store._workspace._paths)
    assert all(not path.exists() for path in paths)


def test_review011_readers_borrow_independent_handles_and_keep_tie_order(site_root, seo_config):
    import lxml.etree as etree
    for path in (site_root / 'content').rglob('*.xml'):
        tree = etree.parse(str(path))
        tree.find('date').text = '2024-01-01'
        tree.write(str(path))
    cli, config = seo_config
    with capture_site(cli, config, site_root) as snapshot:
        first, second = snapshot.articles(), snapshot.articles()
        assert next(first).slug == next(second).slug == 'first-post'
        first.close()
        assert [article.slug for article in second] == ['second-post', 'premier-article']
        assert [article.slug for article in snapshot.articles()] == ['first-post', 'second-post', 'premier-article']
        assert retained_storage(snapshot)[0] == 5
        retained = snapshot.articles()
        next(retained)
        paths = list(snapshot._store._workspace._paths)
    with pytest.raises(ValueError, match='closed'):
        next(retained)
    assert all(not path.exists() for path in paths)


def test_review011_sort_failure_settles_owned_files_on_context_exit(site_root, seo_config, monkeypatch):
    from articulous import pipeline
    cli, config = seo_config
    write = pipeline._write_sorted_article_chunk
    paths = []

    def fail(workspace, articles):
        write(workspace, articles)
        paths.extend(workspace._paths)
        raise OSError('sort failure after allocation')

    snapshot = None
    with pytest.raises(OSError, match='sort failure'):
        with capture_site(cli, config, site_root) as snapshot:
            monkeypatch.setattr(pipeline, '_write_sorted_article_chunk', fail)
            next(snapshot.articles())
    assert snapshot is not None
    assert snapshot._active == set()
    assert paths
    assert all(not path.exists() for path in paths)
