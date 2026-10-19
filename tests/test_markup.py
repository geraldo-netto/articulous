"""I18N-001/REV-059/081/083/121/134: markup preservation and borrow settlement."""
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import random
import pytest
import lxml.etree as etree
from articulous import markup
from articulous.markup_contracts import MarkupPolicy


@pytest.mark.parametrize('source', [
    '<p>Hello<!-- private --> world <b>bold</b><?note private?> end</p>',
    '<p><b>A<!-- note -->B<?note x?>C</b></p>',
    '<p>Text &amp; &lt; 2<code>x &lt; 3</code> end<br/><img alt="Text"/></p>',
    '<p> Text <span translate="no">Keep</span> <span/> </p>',
    '<blockquote><p>Block</p><pre>Code</pre></blockquote>',
])
def test_rev059_rev121_exact_round_trip(source):
    block = etree.fromstring(source)
    before = etree.tostring(block)
    encoded = markup.encode_block(block)
    assert markup.decode_block(block, encoded.text, encoded)
    assert etree.tostring(block) == before
    assert encoded.root is None and not encoded.slots and not encoded.snapshot
    assert not markup.decode_block(block, encoded.text, encoded)


@pytest.mark.parametrize('source,translated', [
    ('<p><b>Bold</b><em>Em</em></p>', '<z2>Énfasis</z2><z1>Negrita</z1>'),
    ('<p><b><em>Em</em><a href="/x">Link</a></b></p>', '<z1><z3>Enlace</z3><z2>Énfasis</z2></z1>'),
])
def test_rev083_inline_reordering(source, translated):
    block = etree.fromstring(source)
    encoded = markup.encode_block(block)
    assert markup.decode_block(block, translated, encoded)
    assert markup.markup_signature(block) == markup.markup_signature(etree.fromstring(source))


@pytest.mark.parametrize('source,translated', [
    ('<p><b>Bold</b><em>Em</em></p>', '<z1>Negrita<z2>Énfasis</z2></z1>'),
    ('<p><b><em>Em</em></b></p>', '<z1>Negrita</z1><z2>Énfasis</z2>'),
    ('<p><code>keep</code></p>', '<z1>changed</z1>'),
    ('<p><span translate="no">keep</span></p>', '<z1>changed</z1>'),
    ('<p><b>Bold</b></p>', '<z1 injected="yes">Negrita</z1>'),
    ('<p><b>Bold</b></p>', '<z01>Negrita</z01>'),
    ('<p><b>Bold</b></p>', '<z0>Negrita</z0>'),
    ('<p><b>Bold</b></p>', '<z1>one</z1><z1>duplicate</z1>'),
    ('<p><b>Bold</b></p>', ''),
    ('<p><b>Bold</b></p>', '<broken'),
    ('<blockquote><p id="one">One</p><p id="two">Two</p></blockquote>', '<z2>Dos</z2><z1>Uno</z1>'),
])
def test_i18n001_rejection_preserves_borrowed_child_identities(source, translated):
    block = etree.fromstring(source)
    children = tuple(block)
    before = etree.tostring(block)
    encoded = markup.encode_block(block)
    assert not markup.decode_block(block, translated, encoded)
    assert tuple(block) == children
    assert etree.tostring(block) == before
    assert encoded.root is None and not encoded.slots


def test_i18n001_borrow_identity_and_snapshot_cutoff():
    block = etree.fromstring('<p>Original</p>')
    encoded = markup.encode_block(block)
    assert not markup.decode_block(deepcopy(block), 'Changed', encoded)
    encoded = markup.encode_block(block)
    block.text = 'Owner edit'
    assert not markup.decode_block(block, 'Changed', encoded)
    assert block.text == 'Owner edit'
    encoded = markup.encode_block(block)
    encoded.close()
    encoded.close()
    assert not markup.decode_block(block, 'Changed', encoded)


def test_i18n001_custom_policy_and_link_projection():
    policy = replace(MarkupPolicy(), opaque_tags=MarkupPolicy().opaque_tags | {'widget'})
    block = etree.fromstring('<p><widget>Secret</widget><a href="/old/" title="Title">Link</a></p>')
    encoded = markup.encode_block(block, policy)
    assert 'Secret' not in encoded.text
    assert markup.decode_block(block, '<z1/><z2>Enlace</z2>', encoded, policy)
    target = deepcopy(block)
    target.find('a').set('href', '/new/')
    target.find('a').set('title', 'Título')
    assert markup.markup_signature(block, policy, rewrite_link=new_link) == markup.markup_signature(target, policy)
    assert markup.markup_signature(block, policy, links=False) == markup.markup_signature(target, policy, links=False)


def new_link(value):
    return '/new/'


@pytest.mark.parametrize('text,wanted,xml,valid', [
    ('', [], True, False), ('plain', [], False, True), ('<z1/>', [], True, False),
    ('<z1/>', ['<z1/>'], True, True), ('<z1 x="1"/>', [], True, False),
    ('<z1>', ['<z1>'], True, False), ('<b/>', [], True, False),
    ('<!-- hidden -->', [], True, False), ('<z1 a="1"/>', ['<z1 a="1"/>'], True, False),
])
def test_i18n001_untrusted_provider_text(text, wanted, xml, valid):
    assert markup.usable_translation(text, wanted, xml) is valid


def test_i18n001_bounded_bad_placeholders_and_inline_properties():
    randomizer = random.Random(81)
    for _ in range(32):
        block = etree.fromstring('<p><b>Bold</b></p>')
        encoded = markup.encode_block(block)
        identifier = randomizer.choice(['0', '01', '9' * 5000, str(randomizer.randrange(2, 10000))])
        assert not markup.decode_block(block, '<z' + identifier + '/>', encoded)
    children = ['<b id="one">Bold</b>', '<em>Emphasis</em>', '<code>Keep</code>']
    original = markup.markup_signature(etree.fromstring('<p>' + ''.join(children) + '</p>'))
    for ordering in permutations(children):
        assert markup.markup_signature(etree.fromstring('<p>' + ''.join(ordering) + '</p>')) == original


def test_rev134_block_selection_and_loose_prose():
    body = etree.fromstring('<body>Loose<!-- note --> tail<p>Block <b>bold</b></p><pre><p>Code</p></pre><span translate="no"><p>Skip</p></span><div>Other <i>inline</i> tail</div><blockquote><p>Nested</p></blockquote></body>')
    blocks = markup.block_units(body)
    assert [node.tag for node in blocks] == ['p', 'blockquote']
    units = markup.loose_text_nodes(body, blocks)
    assert [(node.tag if isinstance(node.tag, str) else 'comment', kind) for node, kind in units] == [('body', 'text'), ('comment', 'tail'), ('div', 'text'), ('i', 'text'), ('i', 'tail')]
    assert markup.in_skipped(body.find('span'))
    assert markup.in_skipped(body.find('span/p'))
    assert markup.in_skipped(body.find('pre/p'))


@pytest.mark.parametrize('text', ['\x00', '\ud800', '\uffff'])
def test_i18n001_invalid_unicode_is_rejected_without_mutation(text):
    block = etree.fromstring('<p>Original</p>')
    encoded = markup.encode_block(block)
    assert not markup.usable_translation(text, [], True)
    assert not markup.decode_block(block, text, encoded)
    assert block.text == 'Original'
    assert encoded.root is None
