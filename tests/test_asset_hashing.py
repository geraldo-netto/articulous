"""Asset type changes must fail instead of blocking fingerprint reads."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from articulous.runtime import file_hash


def test_file_hash_rejects_symlink_aliases(tmp_path):
    target = tmp_path / "target"
    target.write_text("data")
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    with pytest.raises(OSError):
        file_hash(alias)


def test_asset_replaced_by_fifo_before_hashing_fails_promptly(site_root):
    script = '''
from pathlib import Path
import os
import articulous.pipeline as pipeline
from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config
root = Path.cwd()
cli = CliOptions(parse_cli_args([]))
config = load_or_create_config(root / "config.json")
apply_cli_overrides(config, cli, root)
ctx = pipeline.build_ctx_from_config(config, False)
original_hash = pipeline.file_hash
def change_before_hash(path):
    path.unlink()
    os.mkfifo(path)
    return original_hash(path)
pipeline.file_hash = change_before_hash
pipeline.copy_assets(ctx, {})
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-c", script], cwd=site_root, env=environment,
                            capture_output=True, timeout=5)
    assert result.returncode != 0
    assert b"must be a regular file" in result.stderr
    assert not (site_root / "output/assets").exists()
