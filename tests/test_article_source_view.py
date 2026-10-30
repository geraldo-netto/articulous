"""BUILD-038: shared source capture admits metadata and edits with one XML parse."""
from pathlib import Path
from unittest.mock import patch
import pytest
from articulous import articles


def test_build038_parse_once_and_keep_original_bytes(site_root):
    from articulous.xml_sources import read_source
    path = site_root / 'content/en/first-post.xml'
    before = path.read_bytes()
    with patch.object(articles.etree, 'fromstring', wraps=articles.etree.fromstring) as parse:
        source = read_source(path)
        article = articles.parse_article_source(path, source)
    assert parse.call_count == 1
    assert article.source_xml == before
    assert article.slug == 'first-post'
    source.root.find('title').text = 'Edited private copy'
    assert b'Edited private copy' in source.serialize()
    assert path.read_bytes() == before
    assert article.title == 'First Post'


def test_build038_invalid_source_contracts_reject_before_metadata(site_root):
    from articulous.xml_contracts import XmlSource
    from articulous.xml_sources import read_source
    source = read_source(site_root / 'content/en/first-post.xml')
    fields = {'content': source.content, 'base_uri': source.base_uri,
              'root': source.root, 'serialize': source.serialize}
    for name, values in {'content': ('xml', b''), 'base_uri': (None, ''),
                          'root': (None, object()), 'serialize': (None, 1)}.items():
        for value in values:
            with pytest.raises((TypeError, ValueError)):
                XmlSource(**{**fields, name: value})
    with pytest.raises(TypeError):
        articles.parse_article_source(Path('source.xml'), object())
    with pytest.raises(TypeError):
        articles.parse_article_source('source.xml', source)


def test_build038_reader_preserves_safe_xml_and_regular_file_admission(tmp_path):
    from articulous.xml_sources import read_source
    path = tmp_path / 'input.xml'
    path.write_text('<article><title>Title</title><date>invalid</date></article>')
    assert articles.parse_article_source(path, read_source(path)) is None
    link = tmp_path / 'link.xml'
    link.symlink_to(path)
    with pytest.raises((OSError, ValueError)):
        read_source(link)
    path.write_text('<broken')
    with pytest.raises(articles.etree.XMLSyntaxError):
        read_source(path)
