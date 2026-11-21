"""HTML5-001: finite independent lexical/namespace oracles and invalid controls."""
import random
from html.parser import HTMLParser
import pytest
from articulous.html_serialization import html5_void_ends, _VoidEnds


@pytest.mark.parametrize('value', [None, False, 0, [], {}, b'<source></source>'])
def test_html5_001_projection_rejects_non_text(value):
    with pytest.raises(ValueError):
        html5_void_ends(value)


@pytest.mark.parametrize('source,expected', [
    ('', ''), ('plain text', 'plain text'),
    ('<source\n title="</source>"></source>', '<source\n title="</source>">'),
    ('<div><source/></div>', '<div><source/></div>'),
    ('<div><source/></div><br></BR>', '<div><source/></div><br>'),
    ('<svg><source/></svg><source></source>', '<svg><source/></svg><source>'),
    ('<div/></unexpected><source></source>', '<div/></unexpected><source>'),
    ('<plaintext><source></source></plaintext><source></source>',
     '<plaintext><source></source></plaintext><source></source>'),
    ('<math><source></source><mtext><source></source><mglyph><source></source></mglyph></mtext></math>',
     '<math><source></source><mtext><source><mglyph><source></source></mglyph></mtext></math>'),
    ('<math><annotation-xml encoding="TEXT/HTML"><source></source></annotation-xml></math>',
     '<math><annotation-xml encoding="TEXT/HTML"><source></annotation-xml></math>'),
    ('<math><annotation-xml encoding="other"><source></source></annotation-xml></math>',
     '<math><annotation-xml encoding="other"><source></source></annotation-xml></math>'),
    ('<math><annotation-xml><source></source></annotation-xml></math>',
     '<math><annotation-xml><source></source></annotation-xml></math>'),
])
def test_html5_001_context_and_boundary_controls(source, expected):
    assert html5_void_ends(source) == expected


@pytest.mark.parametrize('tag', ['script', 'style', 'textarea', 'title', 'xmp', 'iframe', 'noembed', 'noframes'])
def test_html5_001_raw_context_does_not_lose_literal_end_tags(tag):
    source = f'<{tag}></source></{tag}><source></source>'
    assert html5_void_ends(source) == f'<{tag}></source></{tag}><source>'


def test_html5_001_bounded_unicode_whitespace_and_literal_interleavings():
    randomizer = random.Random(197)
    literals = ['é', '\n', '\r\n', '🎨', '<!--</source>-->', '<pre>&lt;/source&gt;</pre>',
                '<script>"</source>"</script>', '<svg><source></source></svg>']
    for size in range(65):
        before, after = [], []
        for _ in range(size):
            literal = randomizer.choice(literals)
            tag = randomizer.choice(['source', 'track', 'wbr', 'embed', 'SOURCE'])
            before.append(literal + f'<{tag}></{tag}>')
            after.append(literal + f'<{tag}>')
        assert html5_void_ends(''.join(before)) == ''.join(after)


def test_html5_001_late_callbacks_after_plaintext_cannot_change_output():
    parser = _VoidEnds('<plaintext><source></source>')
    parser.feed('<plaintext>')
    before = list(parser.stack)
    # Older supported Python parsers deliver these callbacks after plaintext.
    parser.handle_starttag('source', [])
    parser.handle_endtag('source')
    assert parser.stack == before
    assert parser.omissions == []


def test_perf14_candidate_free_source_bypasses_tokenizer(monkeypatch):
    from articulous import html_serialization

    def unexpected(_source):
        raise AssertionError('candidate-free output must bypass the tokenizer')

    monkeypatch.setattr(html_serialization, '_VoidEnds', unexpected)
    source = '<p>é<a>exact</a><linK></linK><br></p>'
    assert html5_void_ends(source) is source


def test_rel41_unterminated_legacy_token_is_preserved(monkeypatch):
    def legacy_end(parser, index):
        parser.handle_endtag('br')
        return parser.rawdata.index('>', index) + 1

    monkeypatch.setattr(HTMLParser, 'parse_endtag', legacy_end)
    source = '<br></br a=">unterminated'
    assert html5_void_ends(source) == source


def test_review28_09_script_escapes_keep_double_escaped_text():
    data = '<!--<script/label></script>keep</source></script>'
    assert html5_void_ends(f'<script>{data}<source></source>') == f'<script>{data}<source>'


@pytest.mark.parametrize('attributes,remaining', [
    (' "><p>kept</p> "x>tail', '<p>kept</p> "x>tail'),
    (' x=n">rest', 'rest'), (' q = "n>m">é', 'é'),
    (" q='x>unterminated", None), (' =>rest', 'rest'),
    (' ="x>rest', 'rest'), (' a ==x>rest', 'rest'),
    (' q=a/b>rest', 'rest'), (' a/ =b>rest', 'rest'),
    (' q= ', None), (' attr', None), ('', None),
])
def test_review28_09_end_tags_follow_attribute_states(attributes, remaining):
    source = '</source' + attributes
    assert html5_void_ends(source) == (source if remaining is None else remaining)


def test_review28_09_seeded_script_states_match_html5lib():
    from html5lib import parseFragment

    rng = random.Random(2809)
    chunks = ['<script>', '<ScRiPt/', '<script ', '<scriptx>', '<script=>',
              '<!--', '<!-->', '-->', '--', '<', '!', 'é', '</scriptx>', '--!>']
    for _ in range(450):
        lead = ''.join(rng.choices(chunks, k=rng.randrange(18)))
        head = '<script>' + lead + '</script>kept'
        tail = '<p>inside?</p></script><source>'
        source = head + '</source>' + tail + '</source>'
        script = parseFragment(source, namespaceHTMLElements=False).find('script')
        retained = '</source>' if '</source>' in (script.text or '') else ''
        assert html5_void_ends(source) == head + retained + tail


def test_review28_09_seeded_attribute_ends_match_html5lib():
    from html5lib._tokenizer import HTMLTokenizer
    from html5lib.constants import tokenTypes

    rng = random.Random(2908)
    pieces = ['=', 'x', "'", '"', '/', '<', '>', ' ', '\t', 'é', '0']
    for _ in range(450):
        source = '</source ' + ''.join(rng.choices(pieces, k=rng.randrange(32))) + '>tail'
        tokenizer = HTMLTokenizer(source)
        expected = source
        for token in tokenizer:
            if token.get('type') == tokenTypes['EndTag'] and token.get('name') == 'source':
                expected = source[tokenizer.stream.position()[1]:]
                break
        assert html5_void_ends(source) == expected


@pytest.mark.parametrize('source', [
    '<script>raw</source>',
    '<script/><!--<script></script>still script</source>',
    '<script>data</script q="unfinished>literal</source>',
    '<script><!--><script>data</source></script>',
])
def test_review28_09_script_eof_keeps_original_serialization(source):
    assert html5_void_ends(source) == source
