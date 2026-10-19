"""I18N-002: optional provider/cache/XML/job boundaries, entirely offline."""
from contextlib import contextmanager
import io
import json
import sqlite3
from unittest.mock import patch

import pytest
import lxml.etree as etree
from articulous.backends import translation_http
from articulous.translation_cache import open_cache
from articulous.translation_client import Translator
from articulous.translation_contracts import TranslationJob, XmlTranslationLayout
from articulous.translation_jobs import (collect_variants, file_budget, pending_jobs, resolve_original,
                                         run_jobs, select_original, validate_languages)
from articulous.translation_xml import mirror_xml
from articulous.markup_contracts import MarkupPolicy


class Provider:
    model = 'fake-model'
    identity = ('fake', 'model', 0.2)

    def post(self, system, user):
        return user.upper()


def prompt(source, target, xml):
    return json.dumps([source, target, xml])


def normalize(value):
    return value.strip()


@contextmanager
def client():
    with open_cache(':memory:') as cache:
        yield Translator(Provider(), cache, prompt, normalize, record_log)


def record_log(*parts):
    pass


def digest(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()[:16]


def test_i18n002_client_cache_identity_and_borrow():
    with client() as translator:
        assert translator.model == 'fake-model'
        assert translator.translate('  ', 'aa', 'bb') == '  '
        assert translator.translate('Prose', 'aa', 'bb') == 'PROSE'
        assert translator.translate('Prose', 'aa', 'bb') == 'PROSE'
        assert translator.calls == translator.cache_hits == 1
        key = translator._key('Prose', 'aa', 'bb')
        translator._store(key, ' ')
        assert translator.translate('Prose', 'aa', 'bb') == 'PROSE'
        translator._store(key, b'poison')
        assert translator.translate('Prose', 'aa', 'bb') == 'PROSE'
        assert translator._key('Prose', 'aa', 'bb', False) != key
        assert translator.translate('Plain', 'aa', 'bb', False) == 'PLAIN'
    with pytest.raises(sqlite3.ProgrammingError):
        translator.cache.get(key)


@pytest.mark.parametrize('invalid', [-1, True, '2', 1.5])
def test_i18n002_invalid_retry_budget(invalid):
    with open_cache(':memory:') as cache:
        with pytest.raises(ValueError, match='retries'):
            Translator(Provider(), cache, prompt, normalize, record_log, retries=invalid)


@pytest.mark.parametrize('responses', [[TimeoutError('timeout'), 'Fixed'], ['', 'Fixed'], [False, 'Fixed'], ['', '', ''], [ConnectionResetError('reset')] * 3])
def test_i18n002_retry_fault_controls(responses, monkeypatch):
    from articulous import translation_client
    monkeypatch.setattr(translation_client.time, 'sleep', record_log)
    with client() as translator, patch.object(translator, '_post', side_effect=responses):
        expected = 'Fixed' if responses[-1] == 'Fixed' else None
        assert translator.translate('Prose', 'aa', 'bb') == expected
        assert translator.calls == len(responses)


@pytest.mark.parametrize('body', [{}, [], {'choices': []}, {'choices': [None]}, {'choices': [{'message': {'content': None}}]}, {'choices': [{'message': {'content': 4}}]}, {'choices': [{'message': {'content': '  Result  '}}]}])
def test_i18n002_native_provider_schema_and_response_close(body):
    response = io.BytesIO(json.dumps(body).encode())
    provider = translation_http.HttpProvider('http://unused/', 'model', .3, 2)
    assert provider.identity == ('openai-compatible', 'http://unused', 'model', .3)
    with patch.object(translation_http.urllib.request, 'urlopen', return_value=response) as opened:
        if body == {'choices': [{'message': {'content': '  Result  '}}]}:
            assert provider.post('System', 'User') == 'Result'
        else:
            with pytest.raises(translation_http.urllib.error.URLError, match='Invalid translation response'):
                provider.post('System', 'User')
    assert response.closed
    request = opened.call_args.args[0]
    assert request.full_url == 'http://unused/v1/chat/completions'
    assert json.loads(request.data)['stream'] is False


@pytest.mark.parametrize('attributes', [False, True])
@pytest.mark.parametrize('failure', [False, True])
def test_i18n002_mirror_schema_and_failed_provenance(tmp_path, attributes, failure):
    source, target = tmp_path / 'original.xml', tmp_path / 'translated.xml'
    source.write_text('<entry title="Title" description="Description" source-hash="inherited"><title>Title</title><description>Description</description><language>aa</language><source-hash>inherited</source-hash><body> Loose <span>inline</span> end<p>Prose <b>bold</b></p><p> </p><pre title="keep">Code</pre><img alt="Image" title=""/><a href="/path">Link</a><a>Blank</a><pre><a href="/keep">Keep</a></pre><!-- note --></body></entry>')
    layout = XmlTranslationLayout(('title', 'description'), attributes, attributes, 'language', digest)
    with client() as translator, patch.object(translator, '_post', side_effect=empty if failure else echo):
        stats = {'units': 0, 'failed': 0}
        mirror_xml(source, target, 'aa', 'bb', translator, stats, layout, MarkupPolicy(), record_log, rewrite_link=normalize)
    root = etree.parse(str(target)).getroot()
    value = root.get('source-hash') if attributes else root.findtext('source-hash')
    assert value == (None if failure else digest(source.read_bytes()))
    assert root.findtext('language') == 'bb'
    assert root.findtext('body/pre') == 'Code'
    assert bool(stats['failed']) is failure


def echo(system, user):
    return user


def empty(system, user):
    return ''


@pytest.mark.parametrize('change', ['source', 'target', 'late-source'])
def test_rev072_rev073_source_and_target_changes_preserve_target(tmp_path, change):
    source, target = tmp_path / 'source.xml', tmp_path / 'target.xml'
    source.write_text('<entry><title>Title</title><body><p>Prose</p></body></entry>')
    target.write_bytes(b'original')
    layout = XmlTranslationLayout(('title', 'absent'), False, False, None, digest)
    def changed(system, user):
        (source if change == 'source' else target).write_bytes(b'owner edit')
        return user
    with client() as translator:
        if change == 'late-source':
            from articulous import translation_xml
            original = translation_xml.replace_file
            def late(path, writer):
                source.write_text('<entry>Owner edit</entry>')
                return original(path, writer)
            with patch.object(translation_xml, 'replace_file', late), pytest.raises(ValueError, match='source changed'):
                mirror_xml(source, target, 'aa', 'bb', translator, {'units': 0, 'failed': 0}, layout, MarkupPolicy(), record_log)
        else:
            with patch.object(translator, '_post', side_effect=changed), pytest.raises(ValueError, match='changed'):
                mirror_xml(source, target, 'aa', 'bb', translator, {'units': 0, 'failed': 0}, layout, MarkupPolicy(), record_log)
    assert target.read_bytes() == (b'owner edit' if change == 'target' else b'original')
    assert not list(tmp_path.glob('.articulous-edit-*'))


def test_i18n002_neutral_missing_fields_and_language(tmp_path):
    source, target = tmp_path / 'source.xml', tmp_path / 'target.xml'
    source.write_text('<entry/>')
    layout = XmlTranslationLayout(('missing',), True, True, 'language', digest)
    with client() as translator:
        mirror_xml(source, target, 'aa', 'bb', translator, {'units': 0, 'failed': 0}, layout, MarkupPolicy(), record_log)
    assert etree.parse(str(target)).getroot().get('source-hash') == digest(source.read_bytes())


@pytest.mark.parametrize('limit', [-1, True, '1', 1.5])
def test_i18n002_invalid_file_budgets(limit):
    with pytest.raises(ValueError, match='limit'):
        file_budget([], limit)


@pytest.mark.parametrize('languages', ['aa', b'aa', [''], ['..'], ['aa', 'AA'], ['aa', 1], ['aa/bb'], None, False, {}])
def test_i18n002_invalid_language_inputs(languages):
    with pytest.raises(ValueError, match='Languages'):
        validate_languages(languages)


def test_i18n002_job_planning_and_queue_fences(tmp_path):
    sources = tmp_path / 'sources'
    (sources / 'aa').mkdir(parents=True)
    source = sources / 'aa/item.xml'
    source.write_text('source')
    assert collect_variants(sources, ['aa', 'bb']) == {'item.xml': {'aa': source}}
    jobs = [TranslationJob(source, tmp_path / f'{index}.xml', 'aa', 'bb', str(index)) for index in range(3)]
    assert file_budget(jobs, None) == file_budget(jobs, 0) == jobs
    assert file_budget(jobs, 1) == jobs[:1]
    assert file_budget(jobs, 10) == jobs
    jobs[0].target.write_text('handwritten')
    jobs[1].target.write_text('current')
    assert pending_jobs(jobs, generated, current) == jobs[2:]
    assert pending_jobs(jobs, generated, current, force=True) == jobs[1:]
    jobs[1].target.write_text('stale')
    assert pending_jobs(jobs, generated, current) == jobs[1:]
    completed = []
    run_jobs(jobs, completed.append)
    assert completed == jobs
    with pytest.raises(ValueError, match='Duplicate'):
        run_jobs([jobs[0], jobs[0]], completed.append)
    def edit_next(job):
        jobs[1].target.write_text('owner edit')
    with pytest.raises(ValueError, match='target changed'):
        run_jobs(jobs, edit_next)


def generated(path):
    return path.read_text() != 'handwritten'


def current(job):
    return job.target.read_text() == 'current'


def test_i18n002_original_selection_and_confinement(tmp_path):
    source, mirror = tmp_path / 'original', tmp_path / 'mirror'
    source.write_text('source')
    mirror.write_text('mirror')
    def read(path):
        return ('aa', None) if path == source else ('bb', source)
    def resolve(path):
        return resolve_original(path, tmp_path, read)
    assert select_original({'bb': mirror}, 'bb', resolve) == ('aa', source)
    assert select_original({'aa': source, 'bb': mirror}, 'aa', resolve) == ('aa', source)
    with pytest.raises(ValueError, match='unavailable'):
        select_original({}, 'aa', resolve)
    with pytest.raises(ValueError, match='escapes'):
        resolve_original(source, tmp_path / 'elsewhere', read)
    assert resolve_original(mirror, tmp_path, no_origin) is None
    def cyclic(path):
        return 'bb', path
    assert resolve_original(mirror, tmp_path, cyclic) is None
    assert resolve_original(tmp_path / 'missing', tmp_path, read) is None


def no_origin(path):
    return None


def test_i18n002_unresolvable_variant(tmp_path):
    with pytest.raises(ValueError, match='unavailable'):
        select_original({'aa': tmp_path / 'missing'}, 'aa', no_origin)


def test_i18n002_one_prompt_snapshot_per_request():
    prompts = []
    def changing_prompt(source, target, xml):
        prompts.append(str(len(prompts)))
        return prompts[-1]
    with open_cache(':memory:') as cache:
        translator = Translator(Provider(), cache, changing_prompt, normalize, record_log)
        assert translator.translate('Prose', 'aa', 'bb') == 'PROSE'
        assert len(prompts) == 1, 'I18N-002: cache identity and provider must use the same prompt snapshot'
