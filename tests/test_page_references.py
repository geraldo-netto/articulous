"""BUILD-037: detached canonical references from one borrowed parsed document."""
from lxml import html
from articulous import site_validation


def test_build037_existing_document_extracts_exact_detached_facts():
    source = ('<html><head><base href="/base/"><link rel="canonical" href="/page/">'
              '<meta property="og:image" content="/image.svg"></head><body>'
              '<a id="live" name="old-anchor" href="next?q=1#x">link</a>'
              '<img src="asset.svg"><template><a href="inert" id="hidden">template</a></template>'
              '</body></html>')
    document = html.fromstring(source)
    references = site_validation.page_references(document)
    assert references.canonicals == ('/page/',)
    assert references.links == ('/page/', '/image.svg', 'next?q=1#x', 'asset.svg')
    assert references.anchors == frozenset(('live', 'old-anchor'))
    assert references.base_href == '/base/'
    assert all(type(value) is str for value in references.links)
    document.clear()
    assert references.base_href == '/base/'
    assert references.anchors == frozenset(('live', 'old-anchor'))


def test_build037_reference_projection_does_not_require_concrete_parser_types():
    class EmptySource:
        def xpath(self, expression):
            return ()
    references = site_validation.page_references(EmptySource())
    assert references == ((), (), frozenset(), None)
