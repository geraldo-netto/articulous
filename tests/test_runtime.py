"""Unit tests for articulous.runtime."""
import json
import logging
import os
import threading
import time

import pytest

from articulous.filesystem import (
    TempWorkspace,
    _pid_alive,
    ensure_parent_dir,
    lock_file,
    write_text_atomic,
)
from articulous.runtime import (
    TrackedCache,
    cache_changed,
    file_hash,
    load_cache,
    run_parallel_tasks,
    save_cache,
    should_rebuild,
    timed,
    update_cache,
)


# --- _ensure_parent_dir ---

def test_ensure_parent_dir_creates(tmp_path):
    p = tmp_path / "a" / "b" / "c.txt"
    ensure_parent_dir(p)
    assert p.parent.is_dir()


def test_ensure_parent_dir_dry_run_noop(tmp_path):
    p = tmp_path / "a" / "b" / "c.txt"
    ensure_parent_dir(p, dry_run=True)
    assert not p.parent.exists()


def test_ensure_parent_dir_existing_parent_noop(tmp_path):
    p = tmp_path / "c.txt"
    ensure_parent_dir(p)
    assert tmp_path.is_dir()


def test_write_text_atomic_replaces_existing_file(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("old")
    write_text_atomic(p, "new")
    assert p.read_text() == "new"


def test_write_text_atomic_cleans_temp_on_replace_error(tmp_path, monkeypatch):
    p = tmp_path / "x.txt"

    def boom(self, target):
        if target == p:
            raise OSError("replace")
        return original_replace(self, target)

    original_replace = type(p).replace
    monkeypatch.setattr(type(p), "replace", boom)
    with pytest.raises(OSError, match="replace"):
        write_text_atomic(p, "new")
    assert not p.exists()
    assert list(tmp_path.iterdir()) == []


# --- file_hash ---

def test_file_hash_stable(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    h1 = file_hash(p)
    h2 = file_hash(p)
    assert h1 == h2
    assert len(h1) == 64


def test_file_hash_changes_on_content_change(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    h1 = file_hash(p)
    p.write_bytes(b"hellz")
    assert file_hash(p) != h1


def test_file_hash_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_hash(tmp_path / "ghost")


def test_file_hash_directory_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        file_hash(tmp_path)


# --- load_cache / save_cache ---

def test_load_cache_missing_returns_empty(tmp_path):
    assert load_cache(tmp_path / "no.json") == {}


def test_load_cache_round_trip(tmp_path):
    p = tmp_path / "c.json"
    save_cache(p, {"k": [1, 2]})
    assert load_cache(p) == {"k": [1, 2]}


def test_load_cache_invalid_json_warns(tmp_path, caplog):
    p = tmp_path / "c.json"
    p.write_text("not-json")
    with caplog.at_level(logging.WARNING):
        assert load_cache(p) == {}
    assert any("Failed to load cache" in r.message for r in caplog.records)


def test_load_cache_non_dict_rejected(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]")
    assert load_cache(p) == {}


def test_save_cache_parent_created(tmp_path):
    p = tmp_path / "nonexistent_dir" / "c.json"
    save_cache(p, {"k": [1]})
    assert json.loads(p.read_text()) == {"k": [1]}


def test_save_cache_io_error_logged(tmp_path, caplog, monkeypatch):
    p = tmp_path / "c.json"

    def boom(path, text, encoding="utf-8"):
        raise OSError("disk")

    monkeypatch.setattr("articulous.runtime.write_text_atomic", boom)
    with caplog.at_level(logging.ERROR):
        save_cache(p, {"k": [1]})
    assert any("Failed to save cache" in r.message for r in caplog.records)


def test_save_cache_non_serialisable_value_logged(tmp_path, caplog):
    # set() isn't JSON-serialisable; save_cache should log and swallow.
    p = tmp_path / "c.json"
    with caplog.at_level(logging.ERROR):
        save_cache(p, {"k": {1, 2, 3}})
    assert any("Failed to save cache" in r.message for r in caplog.records)
    assert not p.exists()


# --- should_rebuild + update_cache ---

def test_should_rebuild_force():
    assert should_rebuild("k", {"k": ["xml", "xsl"]}, ("xml", "xsl"), force=True)


def test_should_rebuild_no_entry():
    assert should_rebuild("k", {}, ("xml", "xsl"), force=False)


def test_should_rebuild_matching_hashes():
    assert not should_rebuild(
        "k", {"k": ["xml", "xsl"]}, ("xml", "xsl"), force=False,
    )


def test_should_rebuild_when_output_missing(tmp_path):
    assert should_rebuild(
        "k",
        {"k": ["xml", "xsl"]},
        ("xml", "xsl"),
        force=False,
        output_path=tmp_path / "missing.html",
    )


def test_should_not_rebuild_when_output_exists(tmp_path):
    output = tmp_path / "out.html"
    output.write_text("cached")
    assert not should_rebuild(
        "k",
        {"k": ["xml", "xsl"]},
        ("xml", "xsl"),
        force=False,
        output_path=output,
    )


def test_should_rebuild_changed_hashes():
    assert should_rebuild(
        "k", {"k": ["xml", "xsl"]}, ("xml", "new"), force=False,
    )


def test_update_cache_writes_list_form():
    cache = {}
    update_cache(cache, "k", ("a", "b"))
    assert cache == {"k": ["a", "b"]}


def test_tracked_cache_dirty_state():
    cache = TrackedCache({"k": ["a"]})
    assert not cache_changed(cache)
    cache["k"] = ["a"]
    assert not cache_changed(cache)
    cache["k"] = ["b"]
    assert cache_changed(cache)
    cache.mark_clean()
    cache.pop("k")
    assert cache_changed(cache)


def test_tracked_cache_mutator_edges():
    cache = TrackedCache()
    assert not cache_changed(cache)
    cache.clear()
    assert not cache_changed(cache)
    assert cache.pop("missing", None) is None
    assert not cache_changed(cache)
    cache.update({"a": 1})
    assert cache_changed(cache)
    cache.mark_clean()
    cache.clear()
    assert cache_changed(cache)


def test_lock_file_excludes_second_holder(tmp_path):
    path = tmp_path / "build.lock"
    with lock_file(path):
        assert path.exists()
        with pytest.raises(FileExistsError):
            with lock_file(path):
                pytest.fail("second lock holder unexpectedly entered")
    assert not path.exists()


def test_lock_file_recovers_stale_dead_pid(tmp_path, caplog):
    path = tmp_path / "build.lock"
    path.write_text(json.dumps({"pid": 0, "created": time.time()}))
    with caplog.at_level(logging.WARNING):
        with lock_file(path):
            assert json.loads(path.read_text())["pid"] == os.getpid()
    assert any("dead process build lock" in r.message for r in caplog.records)
    assert not path.exists()


def test_lock_file_recovers_expired_lock(tmp_path, caplog):
    path = tmp_path / "build.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "created": 0}))
    with caplog.at_level(logging.WARNING):
        with lock_file(path, stale_after=0):
            assert json.loads(path.read_text())["pid"] == os.getpid()
    assert any("expired build lock" in r.message for r in caplog.records)
    assert not path.exists()


def test_lock_file_does_not_warn_for_fresh_lock(tmp_path, caplog):
    path = tmp_path / "build.lock"
    with caplog.at_level(logging.WARNING):
        with lock_file(path):
            assert path.exists()
    assert not caplog.records


def test_lock_file_rewrites_released_fresh_lock(tmp_path):
    path = tmp_path / "build.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "created": time.time()}))
    with lock_file(path):
        assert json.loads(path.read_text())["pid"] == os.getpid()
    assert not path.exists()


def test_lock_file_recovers_malformed_lock(tmp_path, caplog):
    path = tmp_path / "build.lock"
    path.write_text("not-json")
    with caplog.at_level(logging.WARNING):
        with lock_file(path):
            assert path.exists()
    assert any("malformed build lock" in r.message for r in caplog.records)


def test_pid_alive_handles_os_errors(monkeypatch):
    def missing(pid, signal):
        raise ProcessLookupError

    monkeypatch.setattr("articulous.filesystem.os.kill", missing)
    assert _pid_alive(123) is False

    def denied(pid, signal):
        raise PermissionError

    monkeypatch.setattr("articulous.filesystem.os.kill", denied)
    assert _pid_alive(123) is True


def test_temp_workspace_add_and_cleanup(tmp_path):
    owned = tmp_path / "owned.txt"
    owned.write_text("x")
    with TempWorkspace() as workspace:
        workspace.add(owned)
        f = workspace.named_file("w+b")
        f.write(b"x")
        temp_path = f.name
        f.close()
    assert not owned.exists()
    assert not os.path.exists(temp_path)


def test_update_cache_thread_safe():
    cache = {}

    def writer(i):
        update_cache(cache, f"k{i}", (str(i), "s"))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(cache) == 200


# --- timed ---

def test_timed_logs_duration(caplog):
    with caplog.at_level(logging.DEBUG):
        timed("label", lambda: None)()
    assert any("task label took" in r.message for r in caplog.records)


def test_timed_propagates_exceptions(caplog):
    def boom(): raise ValueError("nope")
    task = timed("bad", boom)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError):
            task()
    assert any("task bad took" in r.message for r in caplog.records)


def test_timed_returns_result():
    assert timed("ok", lambda: 42)() == 42


# --- run_parallel_tasks ---

def test_run_parallel_tasks_returns_results():
    out = run_parallel_tasks([lambda: 1, lambda: 2], max_workers=2)
    assert sorted(out) == [1, 2]


def test_run_parallel_tasks_empty_list():
    assert run_parallel_tasks([], max_workers=2) == []


def test_run_parallel_tasks_auto_workers():
    out = run_parallel_tasks([lambda: 1, lambda: 2], max_workers="auto")
    assert sorted(out) == [1, 2]


def test_run_parallel_tasks_single_failure_reraises(caplog):
    def good(): return 1
    def bad(): raise ValueError("one")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="one"):
            run_parallel_tasks([good, bad], max_workers=2)


def test_run_parallel_tasks_multi_failure_raises_group(caplog):
    """Two failures hitting the pool simultaneously raise as a group."""
    started = threading.Event()
    proceed = threading.Event()

    def bad1():
        started.set()
        # Block until bad2 has also started so both are in flight before
        # either raises. That way no future is cancelled — both errors
        # arrive through the natural ``fut.result()`` path.
        proceed.wait(timeout=2)
        raise ValueError("one")

    def bad2():
        started.wait(timeout=2)
        proceed.set()
        raise RuntimeError("two")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ExceptionGroup) as info:
            run_parallel_tasks([bad1, bad2], max_workers=2)
    types = sorted(type(e).__name__ for e in info.value.exceptions)
    assert types == ["RuntimeError", "ValueError"]


def test_run_parallel_tasks_cancels_pending(caplog):
    """First failure with max_workers=1 cancels the remaining tasks."""
    import time
    def bad(): raise ValueError("first")
    def slow():
        time.sleep(2)
        return 1
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="first"):
            run_parallel_tasks([bad, slow, slow], max_workers=1)
