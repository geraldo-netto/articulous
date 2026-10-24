"""SAXON-001: exact protocol policy and configuration-file borrow lifetime."""
from contextlib import contextmanager
from pathlib import Path
import subprocess

from lxml import etree  # type: ignore[attr-defined]
import pytest

from articulous.engines import SaxonCEngine
from articulous.filesystem import TempWorkspace


@pytest.mark.parametrize('outcome', ['success', 'failure'])
def test_saxon001_configuration_settles_after_native_exit(tmp_path, monkeypatch, outcome):
    paths = []

    def native(command, **kwargs):
        config = Path(next(argument[8:] for argument in command if argument.startswith('-config:')))
        paths.append(config)
        root = etree.parse(str(config)).getroot()
        assert root.tag == '{http://saxon.sf.net/ns/configuration}configuration'
        assert root[0].tag == '{http://saxon.sf.net/ns/configuration}global'
        assert dict(root[0].attrib) == {'allowedProtocols': '#none'}
        assert '-ext:off' in command and '-xi:off' in command
        if outcome == 'failure':
            raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr('articulous.engines.subprocess.run', native)
    engine = SaxonCEngine(tmp_path / 'Transform')
    output = tmp_path / 'out.xml'
    output.write_text('previous')
    if outcome == 'failure':
        with pytest.raises(subprocess.CalledProcessError):
            engine._run_saxon(tmp_path / 'in.xml', tmp_path / 'style.xsl', output)
        assert output.read_text() == 'previous'
    else:
        engine._run_saxon(tmp_path / 'in.xml', tmp_path / 'style.xsl', output)
    assert len(paths) == 1 and not paths[0].exists()


@pytest.mark.parametrize('stage', ['write', 'close'])
def test_saxon001_configuration_failure_retains_output_and_releases_files(tmp_path, monkeypatch, stage):
    allocated = []
    original = TempWorkspace.named_file

    @contextmanager
    def failed_file(workspace, *args, **kwargs):
        with original(workspace, *args, **kwargs) as stream:
            allocated.append(Path(stream.name))
            if stage == 'write':
                raise OSError('configuration storage')
            yield stream
        raise OSError('configuration storage')

    monkeypatch.setattr(TempWorkspace, 'named_file', failed_file)
    output = tmp_path / 'out.xml'
    output.write_text('previous')
    with pytest.raises(OSError, match='configuration storage'):
        SaxonCEngine(tmp_path / 'Transform')._run_saxon(tmp_path / 'in.xml', tmp_path / 'style.xsl', output)
    assert len(allocated) == 1 and not allocated[0].exists()
    assert output.read_text() == 'previous'
