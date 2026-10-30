"""BUILD-040: ordinary source reads cannot invalidate image mutation identity."""
import os
import pytest
from articulous.image_optimization import image_generation, require_image
from articulous.source_transactions import fingerprint


def test_build040_native_read_access_time_is_not_mutation(tmp_path):
    path = tmp_path / 'image.jpg'
    path.write_bytes(b'unchanged')
    modified = path.stat().st_mtime_ns
    os.utime(path, ns=(modified - 86400 * 10**9, modified))
    original = path.stat()
    generation = image_generation(path)
    digest = fingerprint(path)
    current = path.stat()
    assert current.st_mtime_ns == original.st_mtime_ns
    assert current.st_ctime_ns == original.st_ctime_ns
    require_image(path, generation, digest)


def test_build040_same_bytes_replacement_still_rejects(tmp_path):
    path = tmp_path / 'image.jpg'
    path.write_bytes(b'unchanged')
    digest = fingerprint(path)
    generation = image_generation(path)
    replacement = tmp_path / 'replacement.jpg'
    replacement.write_bytes(b'unchanged')
    replacement.replace(path)
    with pytest.raises(ValueError, match='changed'):
        require_image(path, generation, digest)
