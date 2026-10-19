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
