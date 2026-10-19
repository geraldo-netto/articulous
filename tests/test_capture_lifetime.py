"""LIFE-001: retained child iterators cannot outlive captured-source ownership."""
from articulous.builds import prepare_build
from articulous.extensions import BuildComposition


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


def test_life001_snapshot_closes_every_retained_child_reader(site_root, seo_config, monkeypatch):
    cli, config = seo_config
    children = []
    snapshots = []
    readers = []
    def compose(snapshot):
        snapshots.append(snapshot)
        original = snapshot._store.sorted
        def retained(language):
            child = RetainedReader(original(language))
            children.append(child)
            return child
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
            child = FaultyReader(original(language))
            children.append(child)
            return child
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
