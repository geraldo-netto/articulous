"""REVIEW-026: rollback may retire only the transaction's unchanged publication."""
from pathlib import Path
from unittest.mock import patch

import pytest

from articulous.source_transactions import source_transaction


def owner_change(target, kind):
    if kind == 'edit':
        target.write_bytes(b'owner edit')
    elif kind == 'replace':
        replacement = target.with_suffix('.replacement')
        replacement.write_bytes(b'published')
        replacement.replace(target)
    elif kind == 'remove':
        target.unlink()
    else:
        target.chmod(0o400)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('kind', ['edit', 'replace', 'permissions', 'remove'])
def test_review026_preserve_conflicting_target_and_backups(tmp_path, existing, kind):
    root = tmp_path / 'source'
    root.mkdir()
    target = root / 'a.xml'
    if existing:
        target.write_bytes(b'original')
    native_replace = Path.replace

    def fail_second(path, destination):
        if path.name == 'b.xml' and path.parent.name == 'new':
            owner_change(target, kind)
            raise OSError('second publication failed')
        return native_replace(path, destination)

    transaction = None
    with pytest.raises(RuntimeError, match='retained workspace'):
        with source_transaction(root) as transaction:
            transaction.write('a.xml', b'published', force=True)
            transaction.write('b.xml', b'second')
            with patch.object(Path, 'replace', fail_second):
                transaction.publish()
    if kind == 'remove':
        assert not target.exists()
    else:
        expected = b'owner edit' if kind == 'edit' else b'published'
        assert target.read_bytes() == expected
    assert transaction is not None
    assert transaction.recovery_required and transaction.workspace.is_dir()
    if existing:
        assert (transaction.workspace / 'previous/a.xml').read_bytes() == b'original'
    assert not (root / 'b.xml').exists()


def test_review026_uncontended_new_target_is_removed(tmp_path):
    native_replace = Path.replace

    def fail_second(path, destination):
        if path.name == 'b.xml' and path.parent.name == 'new':
            raise OSError('second publication failed')
        return native_replace(path, destination)

    transaction = None
    with pytest.raises(OSError, match='second publication'):
        with source_transaction(tmp_path / 'source') as transaction:
            transaction.write('a.xml', b'published')
            transaction.write('b.xml', b'second')
            with patch.object(Path, 'replace', fail_second):
                transaction.publish()
    assert transaction is not None
    assert not transaction.workspace.exists()
    assert not (tmp_path / 'source').exists()
