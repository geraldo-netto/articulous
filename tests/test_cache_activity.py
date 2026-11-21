"""REVIEW28-27: generation-bound cache activity and crash-safe retirement."""
import json

import pytest

from articulous.cache_activity import CacheActivity, activity_path
from articulous.cache_store import _recover_partition_queue, partition_path
from articulous.filesystem import cache_lock_path, lock_file
from articulous.publication_paths import transaction_path


def _queue(cache, base, destination):
    activity = CacheActivity(cache, base)
    root = str(destination)
    record = {'__generation__': 'a' * 32, '__last_used__': 1}
    activity.touch(root, record, 2)
    assert activity.used(root, record) == 2
    activity.retire(root)
    activity.prepare_retirement()
    return activity, activity_path(base, root)


@pytest.mark.parametrize('value', [[], {}, {'unknown': [0]}, {'unknown': ['slot', 'generation', False, 2]}])
def test_review28_27_invalid_retirement_state_untouched(tmp_path, value):
    base = tmp_path / 'cache'
    activity, _ = _queue(base, base, tmp_path / 'out')
    activity.queue.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Invalid cache activity retirement queue'):
        activity.validate(str(tmp_path / 'out'))
    assert json.loads(activity.queue.read_text()) == value


def test_review28_27_retirement_rejects_outside_root_and_invalid_cache(tmp_path):
    base = tmp_path / 'cache'
    activity, stamp = _queue(base, base, tmp_path.parent / 'out')
    base.write_text('[]')
    with pytest.raises(ValueError, match='Invalid cache roots'):
        activity.recover(tmp_path)
    with pytest.raises(ValueError, match='Invalid activity retirement root'):
        activity.recover(tmp_path, {})
    assert activity.queue.is_file() and stamp.is_file()


def test_review28_27_partial_retirement_waits_for_journal_and_preserves_replaced_touch(tmp_path):
    base = tmp_path / 'cache'
    _, first = _queue(base, base, tmp_path / 'first')
    other = tmp_path / 'other'
    activity, second = _queue(base, base, other)
    transaction = transaction_path(other)
    transaction.mkdir()
    activity.recover(tmp_path, {})
    assert not first.exists()
    remaining = json.loads(activity.queue.read_text())
    assert set(remaining) == {str(other)}
    activity.recover(tmp_path, {})
    assert second.exists()
    assert json.loads(activity.queue.read_text()) == remaining
    transaction.rmdir()
    activity.touch(str(other), {'__generation__': 'b' * 32, '__last_used__': 3}, 4)
    replacement = second.read_bytes()
    activity.recover(tmp_path, {})
    assert second.read_bytes() == replacement
    assert not activity.queue.exists()


def test_review28_27_partition_queue_waits_for_its_cache_lock(tmp_path):
    base = tmp_path / 'cache'
    root = tmp_path / 'out'
    cache = partition_path(base, root)
    cache.parent.mkdir()
    activity, marker = _queue(cache, base, root)
    with lock_file(cache_lock_path(cache)):
        _recover_partition_queue(cache, tmp_path, base)
        assert marker.is_file() and activity.queue.is_file()
    _recover_partition_queue(cache, tmp_path, base)
    assert not marker.exists()
    assert not activity.queue.exists()
