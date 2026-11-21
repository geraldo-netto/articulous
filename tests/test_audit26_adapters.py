"""Adapter regressions from the November project audit."""
import fcntl
from http.client import HTTPConnection
import os
import subprocess
import sys
import time
from unittest.mock import patch

import lxml.etree as etree
import lxml.html as html
import pytest

from articulous import coverage_gate, output_metrics, site_validation
from articulous.backends import browser_fence
from articulous.markup_contracts import MarkupPolicy
from articulous.translation_contracts import XmlTranslationLayout
from articulous.translation_xml import mirror_xml
from test_coverage_name_collisions import native_report
from test_preview import running
from test_translation_authoring import client, digest, record_log


@pytest.mark.parametrize('relation', ['CANONICAL', 'alternate CaNoNiCaL', 'enclosure\tcanonical', 'self\fcanonical'])
def test_audit26_05_only_active_canonical_tokens(relation):
    source = (f'<html><head><link rel="{relation}" href="/right"></head><body>'
              '<template><link rel="canonical" href="/wrong"></template></body></html>')
    assert site_validation.page_references(html.fromstring(source)).canonicals == ('/right',)


def test_audit26_06_even_page_median(tmp_path, capsys):
    for name, size in [('a', 1024), ('b', 9216)]:
        (tmp_path / (name + '.html')).write_bytes(b' ' * size)
    output_metrics.overall(output_metrics.scan(tmp_path))
    assert 'median 5 KB' in capsys.readouterr().out


@pytest.mark.parametrize('regular_file', [True, False])
def test_audit26_07_invalid_coverage_directory(tmp_path, regular_file):
    if regular_file:
        (tmp_path / 'package').touch()
    report = tmp_path / 'coverage.json'
    report.write_text('{}')
    with pytest.raises(SystemExit, match='directory'):
        coverage_gate.main([str(report), '--root', str(tmp_path), '--directory', 'package'])


@pytest.mark.parametrize('namespace,entry', [
    ('urn:other', '<url><loc>/a</loc></url>'),
    ('http://www.sitemaps.org/schemas/sitemap/0.9', '<other><loc>/a</loc></other>'),
    ('http://www.sitemaps.org/schemas/sitemap/0.9', '<url><sub><loc>/a</loc></sub></url>'),
    ('http://www.sitemaps.org/schemas/sitemap/0.9', '<url><loc/><loc>/a</loc></url>'),
    ('http://www.sitemaps.org/schemas/sitemap/0.9', '<url><loc xmlns="urn:other">/a</loc></url>'),
])
def test_audit26_10_invalid_sitemap_structure(tmp_path, namespace, entry):
    path = tmp_path / 'map.xml'
    path.write_text(f'<urlset xmlns="{namespace}">{entry}</urlset>')
    with pytest.raises(ValueError, match='[Ss]itemap'):
        site_validation.sitemap_document(path)


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
def test_audit26_13_missing_preview_fallback(tmp_path, method):
    with running(tmp_path, not_found='/missing.html') as server:
        connection = HTTPConnection('127.0.0.1', server.server_port)
        try:
            connection.request(method, '/unknown')
            response = connection.getresponse()
            assert response.status == 404
            assert response.getheader('Content-Type') == 'text/plain; charset=utf-8'
            assert response.read() == (b'Not found\n' if method == 'GET' else b'')
        finally:
            connection.close()


def translate(source, target, translator):
    layout = XmlTranslationLayout((), False, False, 'lang', digest)
    stats = {'failed': 0, 'units': 0}
    mirror_xml(source, target, 'en', 'fr', translator, stats, layout, MarkupPolicy(), record_log)
    return stats


def test_audit26_17_materialize_target_language(tmp_path):
    source, target = tmp_path / 'en.xml', tmp_path / 'fr.xml'
    source.write_text('<article/>')
    with client() as translator:
        translate(source, target, translator)
    assert etree.parse(str(target)).findtext('lang') == 'fr'


@pytest.mark.parametrize('alias', ['same', 'hardlink', 'symlink'])
def test_audit26_18_preserve_original(tmp_path, alias):
    source = tmp_path / 'en.xml'
    target = source if alias == 'same' else tmp_path / 'alias.xml'
    original = b'<article><body><p>Hello</p></body></article>'
    source.write_bytes(original)
    if alias == 'hardlink':
        target.hardlink_to(source)
    if alias == 'symlink':
        target.symlink_to(source)
    with client() as translator, pytest.raises(ValueError, match='original'):
        translate(source, target, translator)
    assert translator.calls == 0
    assert source.read_bytes() == original


def test_audit26_21_same_line_edit_invalidates_native_coverage(tmp_path):
    source = 'def work():\n    return 1\nwork()\n'
    report, _ = native_report(tmp_path, source)
    assert coverage_gate.check_report(tmp_path, ['code'], report) == (1, [])
    (tmp_path / 'code/example.py').write_text(source.replace('return 1', 'raise RuntimeError()'))
    assert coverage_gate.check_report(tmp_path, ['code'], report)[1]


def test_audit26_22_high_pidfd_exit(tmp_path):
    with subprocess.Popen([sys.executable, '-c', 'pass']) as child:
        descriptor = browser_fence.open_pidfd(child.pid)
        try:
            high = fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 1024)
            try:
                child.wait()
                browser_fence.await_members({child.pid: high}, time.monotonic() + 5)
            finally:
                os.close(high)
        finally:
            os.close(descriptor)


@pytest.mark.parametrize('cached', [False, True])
def test_audit26_24_structural_failure_is_retryable(tmp_path, cached):
    source, target = tmp_path / 'en.xml', tmp_path / 'fr.xml'
    source.write_text('<article><body><p><b>B</b><i>I</i></p></body></article>')
    invalid, valid = '<z1>B<z2>I</z2></z1>', '<z1>Bien</z1><z2>Ici</z2>'
    with client() as translator:
        if cached:
            translator.cache.put(translator._key('<z1>B</z1><z2>I</z2>', 'en', 'fr'), invalid)
        with patch.object(translator, '_post', side_effect=[valid] if cached else [invalid, valid]):
            assert translate(source, target, translator)['failed'] == 0
            assert translate(source, target, translator)['failed'] == 0
        assert translator.calls == (1 if cached else 2)
    assert etree.parse(str(target)).findtext('body/p/b') == 'Bien'


def test_audit26_22_invalid_descriptor_is_not_exit_evidence():
    read, write = os.pipe()
    try:
        assert browser_fence.ready_descriptors([read], 0) == []
    finally:
        os.close(read)
        os.close(write)
    with pytest.raises(OSError, match='exit evidence'):
        browser_fence.ready_descriptors([read], 0)


def test_audit26_09_default_creation_preflight(site_root):
    from articulous.cli import main
    with pytest.raises(ValueError, match='outside the output'):
        main(['--config', 'output/settings.json', '--dry-run'])
    assert not (site_root / 'output').exists()


def test_audit26_24_custom_translation_adapter(tmp_path):
    class Custom:
        model = 'custom'

        def translate(self, text, source, target):
            return text.replace('hello', 'bonjour')

    source, target = tmp_path / 'a.xml', tmp_path / 'b.xml'
    source.write_bytes(b'<article><body><p>hello</p></body></article>')
    assert translate(source, target, Custom())['failed'] == 0
    assert etree.parse(str(target)).findtext('body/p') == 'bonjour'
