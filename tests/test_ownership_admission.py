"""REVIEW-021: malformed recovery records cannot admit owned paths."""
import json
import random

import pytest

from articulous.ownership import load_ownership, ownership_path


@pytest.mark.parametrize('version', [True, False, 1.0, 2.0, None, '2', [], {}])
def test_review021_exact_version_type(tmp_path, version):
    output = tmp_path / 'output'
    data = {'version': version, 'output_dir': str(output), 'outputs': {}, 'paths': {}}
    path = ownership_path(output)
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='ownership version'):
        load_ownership(output)
    assert path.read_bytes() == before


@pytest.mark.parametrize('pending', [False, True])
@pytest.mark.parametrize('position', [0, 1])
def test_review021_invalid_identity_components_preserve_files(tmp_path, pending, position):
    output = tmp_path / 'output'
    output.mkdir()
    target = output / 'manual.txt'
    target.write_bytes(b'keep')
    randomizer = random.Random(21)
    invalid = [-1, -(1 << 128), True, None, 1.0, '1', [], {}]
    invalid.extend(-randomizer.randrange(1, 1 << 64) for _ in range(16))
    for value in invalid:
        identity = [0, 0]
        identity[position] = value
        data = {'version': 2, 'output_dir': str(output), 'paths': {'manual.txt': 'page:manual'},
                'pending': pending, 'existing': {'manual.txt': identity}}
        ownership_path(output).write_text(json.dumps(data))
        with pytest.raises(ValueError, match='publication identities'):
            load_ownership(output)
        assert target.read_bytes() == b'keep'


@pytest.mark.parametrize('identity', [None, [0, 0], [1 << 128, 1 << 128]])
def test_review021_valid_identity_boundaries(tmp_path, identity):
    output = tmp_path / 'output'
    data = {'version': 2, 'output_dir': str(output), 'paths': {'x.html': 'page:x'},
            'pending': True, 'existing': {'x.html': identity}}
    ownership_path(output).write_text(json.dumps(data))
    assert load_ownership(output).paths == {'x.html': 'page:x'}
