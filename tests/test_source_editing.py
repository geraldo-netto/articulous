"""EDIT-001: source edits have their own transaction and resource owner."""
from pathlib import Path
from unittest.mock import patch

import pytest

from articulous.source_files import replace_file
from articulous.source_transactions import SourceChange, SourceTransaction, fingerprint, source_transaction


def test_edit001_atomic_replace_and_writer_failure(tmp_path):
    target = tmp_path / 'nested/file'
    replace_file(target, lambda path: path.write_bytes(b'first'))
    target.chmod(0o640)
    replace_file(target, lambda path: path.write_bytes(b'second'))
    assert target.read_bytes() == b'second'
    assert target.stat().st_mode & 0o777 == 0o640
    with pytest.raises(OSError), patch.object(Path, 'replace', side_effect=OSError('replace')):
        replace_file(target, lambda path: path.write_bytes(b'partial'))
    assert list(target.parent.iterdir()) == [target]
    assert target.read_bytes() == b'second'


@pytest.mark.parametrize('kind', ['content', 'assets'])
def test_review28_57_build_cannot_discover_staged_replacement(tmp_path, kind):
    from articulous.articles import _discover_article_files
    from articulous.pipeline import _asset_manifest

    root = tmp_path / kind
    owner_dir = root / '.owner'
    owner_dir.mkdir(parents=True)
    target = owner_dir / ('entry.xml' if kind == 'content' else 'style.css')
    target.write_bytes(b'published')
    owner_file = owner_dir / '.articulous-source-stage-owner.xml'
    owner_file.write_bytes(b'owner file')
    def write(staged):
        staged.write_bytes(b'unpublished')
        if kind == 'content':
            assert list(_discover_article_files(root)) == [owner_file, target]
        else:
            assert set(_asset_manifest(root)) == {'.owner', '.owner/style.css', '.owner/' + owner_file.name}
        assert target.read_bytes() == b'published'
    replace_file(target, write)
    assert target.read_bytes() == b'unpublished'
    assert set(owner_dir.iterdir()) == {target, owner_file}


@pytest.mark.parametrize('pattern', ['**/*.xml', '*/*/*.xml'])
def test_review28_57_taxonomy_cannot_capture_another_writers_stage(tmp_path, pattern):
    from articulous.taxonomy_editing import _document_paths

    target = tmp_path / 'content' / 'article.xml'
    def write(staged):
        staged.write_bytes(b'<article/>')
        assert _document_paths(tmp_path, pattern) == []
    replace_file(target, write)


def test_review28_57_image_candidates_exclude_staged_replacement(tmp_path):
    from articulous.image_optimization import candidates

    target = tmp_path / 'photo.png'
    target.write_bytes(b'original')
    def write(staged):
        staged.write_bytes(b'smaller')
        assert list(candidates(tmp_path, 0, {'png'})) == [target]
    replace_file(target, write)


def test_edit001_commit_order_permissions_and_conflict(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    old = root / 'old.xml'
    old.write_bytes(b'old')
    old.chmod(0o640)
    with source_transaction(root, final_paths=('manifest.json',)) as transaction:
        transaction.write('old.xml', b'new', force=True)
        transaction.write('manifest.json', b'{}')
        transaction.write('new/nested.xml', b'new')
        assert transaction.changes()[-1] == Path('manifest.json')
    assert old.read_bytes() == b'new'
    assert old.stat().st_mode & 0o777 == 0o640
    with pytest.raises(ValueError, match='edited source'):
        with source_transaction(root) as transaction:
            transaction.write('old.xml', b'different')
    assert fingerprint(root / 'missing') is None


@pytest.mark.parametrize('relative', ['', '.', '..', '../x', '/absolute'])
def test_edit001_invalid_paths_preserve_source(tmp_path, relative):
    with source_transaction(tmp_path) as transaction:
        with pytest.raises(ValueError, match='Invalid source path'):
            transaction.write(relative, b'bad')
    assert not list(tmp_path.iterdir())


def test_edit001_changed_sources_and_symlinks_abort(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    target = root / 'old'
    target.write_bytes(b'old')
    with pytest.raises(ValueError, match='changed during staging'):
        with source_transaction(root) as transaction:
            transaction.capture('old')
            transaction.write('new', b'new')
            target.write_bytes(b'owner edit')
    assert not (root / 'new').exists()
    (root / 'link').symlink_to(target)
    with source_transaction(root) as transaction:
        with pytest.raises(ValueError, match='symlink'):
            transaction.capture('link')


def test_edit001_partial_publication_rolls_back(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    old = root / 'a'
    old.write_bytes(b'old')
    original = Path.replace
    def fail_install(path, destination):
        if path.name == 'b' and path.parent.name == 'new':
            raise OSError('install')
        return original(path, destination)
    with pytest.raises(OSError, match='install'):
        with source_transaction(root) as transaction:
            transaction.write('a', b'new', force=True)
            transaction.write('b', b'new')
            with patch.object(Path, 'replace', fail_install):
                transaction.publish()
    assert old.read_bytes() == b'old'
    assert not (root / 'b').exists()


def test_edit001_manual_recovery_retains_workspace(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    root = tmp_path / 'root'
    root.mkdir()
    backup = workspace / 'backup'
    backup.write_bytes(b'old')
    transaction = SourceTransaction(root, workspace)
    with patch.object(Path, 'replace', side_effect=OSError('restore')):
        with pytest.raises(RuntimeError, match='retained workspace'):
            transaction.rollback([SourceChange(root / 'old', backup, workspace / 'staged', True, None)], [])
    assert transaction.recovery_required
    assert backup.read_bytes() == b'old'


def test_edit001_noop_repeated_capture_and_new_parent(tmp_path):
    root = tmp_path / 'absent/parent/source'
    with source_transaction(root) as transaction:
        transaction.write('file', b'new')
        assert transaction.capture('file') is None
    with source_transaction(root) as transaction:
        transaction.write('file', b'new')
        assert transaction.changes() == []


def test_edit001_publish_detects_late_change(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='changed during publication'):
        with source_transaction(tmp_path) as transaction:
            transaction.write('new', b'new')
            monkeypatch.setattr(transaction, 'changes', lambda: [Path('new')])
            (tmp_path / 'new').write_bytes(b'owner edit')
    assert (tmp_path / 'new').read_bytes() == b'owner edit'


def test_edit001_rollback_directories_and_unmoved_original(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    transaction = SourceTransaction(tmp_path, workspace)
    empty = tmp_path / 'empty'
    empty.mkdir()
    transaction.rollback([SourceChange(tmp_path / 'original', workspace / 'missing', workspace / 'staged', True, None)], [empty])
    assert not empty.exists()
    with pytest.raises(RuntimeError, match='retained workspace'):
        transaction.rollback([], [tmp_path])


def test_edit001_cleanup_failures_report_without_losing_result(tmp_path, capsys):
    from articulous import source_files
    with patch.object(source_files.shutil, 'rmtree', side_effect=OSError('cleanup')):
        with source_transaction(tmp_path) as transaction:
            transaction.write('new', b'new')
    assert (tmp_path / 'new').read_bytes() == b'new'
    assert 'workspace cleanup failed' in capsys.readouterr().err
    with patch.object(source_files.shutil, 'rmtree', side_effect=OSError('cleanup')):
        replace_file(tmp_path / 'single', lambda path: path.write_bytes(b'single'))
    assert 'workspace cleanup failed' in capsys.readouterr().err


def test_edit001_constructor_failure_cleans_workspace(tmp_path):
    with patch('articulous.source_transactions.SourceTransaction', side_effect=RuntimeError('init')):
        with pytest.raises(RuntimeError, match='init'):
            with source_transaction(tmp_path):
                pytest.fail('constructor unexpectedly succeeded')
    assert not list(tmp_path.iterdir())


def test_edit001_failed_context_rollback_keeps_its_owner(tmp_path):
    from articulous import source_files
    def retained(transaction):
        transaction.recovery_required = True
        raise RuntimeError('retained')
    workspace = None
    with patch.object(SourceTransaction, 'publish', retained):
        with pytest.raises(RuntimeError, match='retained'):
            with source_transaction(tmp_path) as transaction:
                workspace = transaction.workspace
    assert workspace is not None
    assert workspace.exists()
    source_files.shutil.rmtree(workspace)


def test_edit001_replaced_workspace_identity_is_preserved(tmp_path):
    original = None
    with pytest.raises(ValueError, match='workspace identity'):
        with source_transaction(tmp_path / 'root') as transaction:
            original = transaction.workspace
            original.rename(tmp_path / 'retained')
            original.mkdir()
            (original / 'owner.txt').write_bytes(b'keep')
    assert original is not None
    assert (original / 'owner.txt').read_bytes() == b'keep'


@pytest.mark.parametrize('kind', ['fifo', 'directory'])
def test_review29_13_capture_rejects_special_files_before_blocking_open(tmp_path, kind):
    import os
    source = tmp_path / 'input.xml'
    if kind == 'fifo':
        os.mkfifo(source)
    else:
        source.mkdir()
    with source_transaction(tmp_path) as transaction:
        with patch.object(Path, 'open', side_effect=AssertionError('unguarded source open')):
            with pytest.raises(ValueError, match='regular file'):
                transaction.capture(source.name)
        assert not transaction.expected
    assert source.exists()
