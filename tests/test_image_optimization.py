"""ASSET-001: explicit image maintenance and its installed native adapter."""
from contextlib import contextmanager
import subprocess
from unittest.mock import patch

import pytest

from articulous.backends.imagemagick import ImageMagick
from articulous.image_contracts import validate_options
from articulous.image_optimization import candidates, optimize


class FakeImages:
    def __init__(self, scratch, content):
        self.scratch = scratch
        self.content = content
        self.closed = False

    @contextmanager
    def workspace(self):
        try:
            yield self.scratch
        finally:
            self.closed = True

    def dimensions(self, path):
        return 100, 80

    def shrink(self, path, target, largest, quality):
        target.write_bytes(self.content)


@pytest.mark.parametrize('apply,content', [(False, b'new'), (True, b'new'), (True, b'larger-than-original')])
def test_asset001_report_apply_and_unchanged(tmp_path, apply, content):
    root = tmp_path / 'images'
    root.mkdir()
    source = root / 'photo.jpg'
    source.write_bytes(b'original')
    (root / 'folder.jpg').mkdir()
    backend = FakeImages(tmp_path, content)
    results = list(optimize(root, backend, largest=1, quality=82, threshold=0,
                            kinds={'jpeg'}, apply=apply))
    assert backend.closed
    assert results[0].before == 8
    assert results[0].after == min(8, len(content))
    assert source.read_bytes() == (content if apply and len(content) < 8 else b'original')
    assert list(candidates(root, 100, {'png'})) == []


@pytest.mark.parametrize('values', [(0, 82, 0), (True, 82, 0), (1, -1, 0), (1, 101, 0),
                                   (1, None, 0), (1, 82, -1), (1, 82, True)])
def test_asset001_invalid_bounds_have_no_effect(tmp_path, values):
    with pytest.raises(ValueError):
        validate_options(*values)
    with patch('articulous.backends.imagemagick.run_owned') as run:
        with pytest.raises(ValueError):
            list(optimize(tmp_path, FakeImages(tmp_path, b'new'), largest=values[0],
                          quality=values[1], threshold=values[2], kinds={'jpeg'}))
        run.assert_not_called()


@pytest.mark.parametrize('suffix,count', [('jpg', 1), ('png', 2)])
def test_asset001_process_contract(tmp_path, suffix, count):
    backend = ImageMagick()
    with patch('articulous.backends.imagemagick.run_owned') as run:
        backend.shrink(tmp_path / ('a.' + suffix), tmp_path / ('b.' + suffix), 1, 100)
    assert run.call_count == count


def test_asset001_native_dimensions_bounds_and_cleanup(tmp_path):
    source = tmp_path / 'native.png'
    subprocess.run(['convert', '-size', '16x8', 'xc:red', str(source)], check=True)
    backend = ImageMagick()
    assert backend.dimensions(source) == (16, 8)
    with backend.workspace() as scratch:
        target = scratch / 'small.png'
        backend.shrink(source, target, 4, 80)
        assert backend.dimensions(target) == (4, 2)
    assert not scratch.exists()


def test_asset001_conversion_failure_closes_workspace(tmp_path):
    root = tmp_path / 'images'
    root.mkdir()
    (root / 'photo.jpg').write_bytes(b'keep')
    backend = FakeImages(tmp_path, b'new')
    with patch.object(backend, 'shrink', side_effect=OSError('conversion')):
        with pytest.raises(OSError, match='conversion'):
            list(optimize(root, backend, largest=1, quality=82, threshold=0, kinds={'jpeg'}))
    assert backend.closed
    assert (root / 'photo.jpg').read_bytes() == b'keep'


def test_asset001_native_jpeg_orientation_and_format(tmp_path):
    import struct
    source = tmp_path / 'oriented.jpg'
    subprocess.run(['convert', '-size', '16x8', 'xc:red', str(source)], check=True)
    original = source.read_bytes()
    tiff = b'II' + struct.pack('<HIH', 42, 8, 1)
    tiff += struct.pack('<HHIHHI', 0x112, 3, 1, 6, 0, 0)
    exif = b'Exif\0\0' + tiff
    source.write_bytes(original[:2] + b'\xff\xe1' + struct.pack('>H', len(exif) + 2) + exif + original[2:])
    backend = ImageMagick()
    with backend.workspace() as scratch:
        target = scratch / 'oriented.jpg'
        backend.shrink(source, target, 4, 82)
        assert backend.dimensions(target) == (2, 4)
        assert target.read_bytes().startswith(b'\xff\xd8')
        assert b'Exif' not in target.read_bytes()


def test_asset001_invalid_native_bounds_never_launch(tmp_path):
    with patch('articulous.backends.imagemagick.run_owned') as run:
        with pytest.raises(ValueError):
            ImageMagick().shrink(tmp_path / 'a.jpg', tmp_path / 'b.jpg', 0, 82)
    run.assert_not_called()


def image_case(tmp_path):
    root = tmp_path / 'images'
    root.mkdir()
    source = root / 'photo.jpg'
    source.write_bytes(b'original source')
    return root, source, FakeImages(tmp_path, b'new')


def apply_images(root, backend):
    return list(optimize(root, backend, largest=1, quality=82, threshold=0,
                         kinds={'jpeg'}, apply=True))


def mutate_image(source, change):
    if change == 'delete':
        source.unlink()
    elif change == 'replace':
        replacement = source.with_suffix('.replacement')
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
    else:
        source.write_bytes(b'concurrent owner edit')


@pytest.mark.parametrize('change', ['edit', 'delete', 'replace'])
def test_review012_conversion_rejects_changed_generation(tmp_path, change):
    root, source, backend = image_case(tmp_path)
    shrink = backend.shrink

    def concurrent_change(*args):
        shrink(*args)
        mutate_image(source, change)

    with patch.object(backend, 'shrink', side_effect=concurrent_change):
        with pytest.raises(ValueError, match='changed during optimization'):
            apply_images(root, backend)
    assert backend.closed
    assert not list(root.glob('.photo.jpg-*'))
    if change == 'delete':
        assert not source.exists()
    else:
        expected = b'original source' if change == 'replace' else b'concurrent owner edit'
        assert source.read_bytes() == expected


def test_review012_rechecks_after_copy_and_releases_lock(tmp_path):
    import shutil
    from articulous.resource_locks import resource_lock
    root, source, backend = image_case(tmp_path)
    copy = shutil.copyfile

    def concurrent_copy(*args):
        copy(*args)
        source.write_bytes(b'late owner edit')

    with patch('articulous.image_optimization.shutil.copyfile', side_effect=concurrent_copy):
        with pytest.raises(ValueError, match='changed during optimization'):
            apply_images(root, backend)
    assert source.read_bytes() == b'late owner edit'
    assert backend.closed
    assert not list(root.glob('.photo.jpg-*'))
    with resource_lock(source.with_name('.photo.jpg.articulous.lock')):
        with pytest.raises(RuntimeError, match='Resource lock is held'):
            apply_images(root, backend)
    assert source.read_bytes() == b'late owner edit'
    assert apply_images(root, backend)[0].after == 3


def test_review012_rejects_symlink_sources(tmp_path):
    root, source, backend = image_case(tmp_path)
    target = root / 'owner'
    source.rename(target)
    source.symlink_to(target)
    with pytest.raises(ValueError, match='regular file'):
        apply_images(root, backend)
    assert backend.closed
    assert target.read_bytes() == b'original source'


def test_review012_content_and_metadata_are_both_checked(tmp_path):
    from articulous.image_optimization import image_generation, require_image
    _, source, _ = image_case(tmp_path)
    generation = image_generation(source)
    with patch('articulous.image_optimization.fingerprint', return_value=b'wrong'):
        with pytest.raises(ValueError, match='changed during optimization'):
            require_image(source, generation, b'expected')
    with patch('articulous.image_optimization.image_generation', side_effect=[generation, None]):
        with pytest.raises(ValueError, match='changed during optimization'):
            require_image(source, generation, __import__('hashlib').sha256(source.read_bytes()).digest())
