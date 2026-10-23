"""PERF-003: one asset materialization per prepared generation."""
import shutil
import time

import pytest

from articulous import pipeline
from articulous.builds import prepare_build, render_prepared, validate_generated
from articulous.extensions import BuildComposition


@pytest.mark.parametrize('composed', [False, True])
def test_perf003_assets_copied_once(site_root, seo_config, monkeypatch, composed):
    cli, config = seo_config
    payload = b'asset payload\0' * 100_000
    (site_root / 'assets/large.bin').write_bytes(payload)
    copies = []
    native_copy = pipeline.copy_asset_file

    def measured_copy(source, destination):
        copies.append(source.stat().st_size)
        native_copy(source, destination)

    monkeypatch.setattr(pipeline, 'copy_asset_file', measured_copy)
    expected = sum(path.stat().st_size for path in (site_root / 'assets').rglob('*') if path.is_file())
    composer = (lambda _: BuildComposition()) if composed else None
    started = time.perf_counter()
    with prepare_build(cli, config, site_root, composer=composer) as prepared:
        captured = prepared.context.assets_dir / 'large.bin'
        identity = captured.stat().st_ino
        (site_root / 'assets/large.bin').write_bytes(b'edited source')
        staged = render_prepared(prepared)
        validate_generated(staged)
        target = staged.root / 'assets/large.bin'
        assert target.read_bytes() == payload
        print(f'PERF-003 composed={composed} copies={len(copies)} bytes={sum(copies)} seconds={time.perf_counter() - started:.6f}')
        assert sum(copies) == expected, 'PERF-003: rendering must not recopy captured assets'
        assert target.stat().st_ino == identity
        assert 'assets' in prepared.cache
    assert not staged.root.exists()


@pytest.mark.parametrize('missing', [False, True])
def test_perf003_empty_and_missing_asset_handoff(site_root, seo_config, missing):
    cli, config = seo_config
    shutil.rmtree(site_root / 'assets')
    if not missing:
        (site_root / 'assets').mkdir()
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        validate_generated(staged)
        assert (staged.root / 'assets').exists() is not missing
    assert not staged.root.exists()
