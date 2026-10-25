"""REVIEW-023: offline distribution installation outside the source checkout."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import tarfile
import sys
import venv
import zipfile

import lxml
import pytest

from articulous.browser_process import run_owned


ROOT = Path(__file__).resolve().parents[1]
BUILD_PYTHON = os.environ.get('ARTICULOUS_BUILD_PYTHON', sys.executable)


def command(arguments):
    return run_owned([str(value) for value in arguments], tooling=False).stdout.strip()


def package_inventory():
    package = ROOT / 'articulous'
    return {path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in package.rglob('*') if path.is_file() and '__pycache__' not in path.parts}


def build_distribution(source, destination, hook):
    destination.mkdir()
    script = ('import os, sys; from setuptools import build_meta; '
              'os.chdir(sys.argv[1]); getattr(build_meta, sys.argv[3])(sys.argv[2])')
    command([BUILD_PYTHON, '-I', '-c', script, source, destination, hook])
    return next(destination.iterdir())


def unpack_source(archive, destination):
    destination.mkdir()
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            assert member.isfile() or member.isdir()
            assert (destination / member.name).resolve().is_relative_to(destination.resolve())
        source.extractall(destination)
    return next(destination.iterdir())


@pytest.fixture(scope='module')
def distributions(tmp_path_factory):
    workspace = tmp_path_factory.mktemp('distributions')
    source = workspace / 'source'
    source.mkdir()
    shutil.copytree(ROOT / 'articulous', source / 'articulous', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copyfile(ROOT / name, source / name)
    with pytest.MonkeyPatch.context() as environment:
        environment.chdir(workspace)
        wheel = build_distribution(source, workspace / 'wheel', 'build_wheel')
        archive = build_distribution(source, workspace / 'sdist', 'build_sdist')
        extracted = unpack_source(archive, workspace / 'unpacked')
        rebuilt = build_distribution(extracted, workspace / 'rebuilt', 'build_wheel')
    return wheel, rebuilt


def require_wheel_inventory(wheel, expected):
    with zipfile.ZipFile(wheel) as archive:
        actual = {name.removeprefix('articulous/'): hashlib.sha256(archive.read(name)).hexdigest()
                  for name in archive.namelist() if name.startswith('articulous/')}
    assert actual == expected, 'REVIEW-023: distribution package bytes differ from source inventory'


def install_wheel(wheel, environment):
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / 'bin/python'
    command([BUILD_PYTHON, '-I', '-m', 'pip', '--isolated', '--python', python,
             'install', '--no-index', '--no-deps', '--no-build-isolation',
             '--disable-pip-version-check', wheel])
    library = Path(command([python, '-I', '-c', "import sysconfig; print(sysconfig.get_path('purelib'))"]))
    shutil.copytree(Path(lxml.__file__).parent, library / 'lxml')
    metadata = importlib.metadata.distribution('lxml')
    assert metadata.files is not None
    record = next(path for path in metadata.files if path.name == 'METADATA')
    shutil.copytree(Path(str(metadata.locate_file(record))).parent, library / record.parent.name)
    return python


def require_installed_resources(python, workspace, expected):
    probe = workspace / 'probe.py'
    shutil.copyfile(ROOT / 'tests/tooling/installed-package.py', probe)
    inventory = workspace / 'expected.json'
    inventory.write_text(json.dumps(expected))
    result = json.loads(command([python, '-I', probe, inventory]))
    assert result['package'].startswith(str(python.parent.parent))
    assert result['tooling'] == 3
    assert result['code'] > 20
    assert result['search'] == 1


def require_installed_build(python, workspace):
    site = workspace / 'site'
    shutil.copytree(ROOT / 'tests/fixtures/site', site)
    with pytest.MonkeyPatch.context() as environment:
        environment.chdir(site)
        assert 'usage:' in command([python.parent / 'articulous', '--help'])
        assert 'usage:' in command([python.parent / 'articulous-preview', '--help'])
        command([python.parent / 'articulous'])
        output = site / 'output'
        assert (output / 'en/articles/first-post/index.html').is_file()
        assert (output / 'fr/articles/premier-article/index.html').is_file()
        assert (output / 'assets/style.css').read_bytes() == (site / 'assets/style.css').read_bytes()
        assert json.loads((output / 'search.json').read_text())
        command([python, '-I', '-m', 'articulous', '--force'])


@pytest.mark.parametrize('index', [0, 1], ids=['wheel', 'sdist-wheel'])
def test_review023_installed_distribution(distributions, tmp_path, monkeypatch, index):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PYTHONPATH', raising=False)
    wheel = distributions[index]
    expected = package_inventory()
    require_wheel_inventory(wheel, expected)
    python = install_wheel(wheel, tmp_path / 'environment')
    require_installed_resources(python, tmp_path, expected)
    require_installed_build(python, tmp_path)


def test_review023_missing_resource_control(distributions):
    expected = package_inventory()
    expected['theme_assets/contracts/missing.d.ts'] = hashlib.sha256(b'missing').hexdigest()
    with pytest.raises(AssertionError, match='REVIEW-023'):
        require_wheel_inventory(distributions[0], expected)
