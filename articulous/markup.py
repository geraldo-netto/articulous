"""Lxml protected-markup codec; provider and language routing stay caller-owned."""
from copy import deepcopy
import re
import lxml.etree as etree
from .markup_contracts import Encoded, MarkupPolicy

DEFAULT_POLICY = MarkupPolicy()
PH = 'z'
PH_RE = re.compile(r'<' + PH + r'(\d+)\s*/>|<' + PH + r'(\d+)>|</' + PH + r'(\d+)>')


def opaque(element, policy=DEFAULT_POLICY):
    return (not isinstance(element.tag, str) or element.tag.lower() in policy.opaque_tags
            or element.get('translate') == 'no')


def attribute_signature(element, policy, rewrite_link, links):
    attributes = []
    for name, value in sorted(element.attrib.items()):
        if name in policy.translatable_attributes:
            value = ''
        elif name in ('href', 'src') and not links:
            value = ''
        elif name == 'href' and rewrite_link is not None:
            value = rewrite_link(value)
        attributes.append((name, value))
    return tuple(attributes)


def markup_signature(element, policy=DEFAULT_POLICY, *, rewrite_link=None, links=True):
    if opaque(element, policy):
        return ('opaque', etree.tostring(element, encoding='unicode', with_tail=False))
    children, inline = [], []
    for child in element:
        signature = markup_signature(child, policy, rewrite_link=rewrite_link, links=links)
        if isinstance(child.tag, str) and child.tag.lower() in policy.inline_tags:
            inline.append(signature)
        else:
            children.extend(sorted(inline))
            inline = []
            children.append(signature)
    children.extend(sorted(inline))
    return element.tag, attribute_signature(element, policy, rewrite_link, links), tuple(children)


def escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def atomic_slot(child, policy):
    return (opaque(child, policy) or child.tag.lower() in policy.void_tags
            or len(child) == 0 and not (child.text or '').strip())


def encode_children(element, out, slots, policy):
    for child in element:
        index = len(slots) + 1
        slots[index] = child
        if atomic_slot(child, policy):
            out.append(f'<{PH}{index}/>')
        else:
            out.append(f'<{PH}{index}>')
            if child.text:
                out.append(escape(child.text))
            encode_children(child, out, slots, policy)
            out.append(f'</{PH}{index}>')
        if child.tail:
            out.append(escape(child.tail))


def encode_block(block, policy=DEFAULT_POLICY):
    out, slots = [], {}
    if block.text:
        out.append(escape(block.text))
    encode_children(block, out, slots, policy)
    return Encoded(''.join(out), block, etree.tostring(block), slots)


def placeholder_signature(text):
    return sorted(match.group(0).replace(' ', '') for match in PH_RE.finditer(text))


def parse_fragment(text):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.fromstring(f'<root>{text}</root>', parser)


def usable_translation(text, wanted, markup):
    if not text.strip() or placeholder_signature(text) != wanted:
        return False
    if not markup:
        return True
    try:
        fragment = parse_fragment(text)
    except etree.XMLSyntaxError:
        return False
    return all(isinstance(node.tag, str) and re.fullmatch(r'z[0-9]+', node.tag)
               and not node.attrib for node in fragment.iterdescendants())


def _slot_placement(node, fragment, original, identities, names, policy):
    expected = identities.get(original.getparent())
    parent = node.getparent()
    actual = None if parent is fragment else names[parent.tag]
    return actual == expected and not (opaque(original, policy) and (node.text or len(node)))


def valid_slots(fragment, slots, policy):
    identities = {node: index for index, node in slots.items()}
    names = {f'{PH}{index}': index for index in slots}
    seen = set()
    for node in fragment.iterdescendants():
        if node.tag not in names or node.attrib:
            return False
        index = names[node.tag]
        if index in seen:
            return False
        seen.add(index)
        if not _slot_placement(node, fragment, slots[index], identities, names, policy):
            return False
    return seen == set(slots)


def rebuild(source, target, slots, policy):
    target.text = source.text
    for node in source:
        original = deepcopy(slots[int(node.tag[1:])])
        if len(node):
            for child in list(original):
                original.remove(child)
            rebuild(node, original, slots, policy)
        elif node.text and original.tag.lower() not in policy.opaque_tags and original.tag.lower() not in policy.void_tags:
            original.text = node.text
        original.tail = node.tail
        target.append(original)


def apply_decoded(block, fragment, encoded, policy):
    candidate = deepcopy(block)
    for child in list(candidate):
        candidate.remove(child)
    rebuild(fragment, candidate, encoded.slots, policy)
    if markup_signature(candidate, policy) != markup_signature(block, policy):
        return False
    block.text = candidate.text
    for child in list(block):
        block.remove(child)
    for child in list(candidate):
        block.append(child)
    return True


def decode_block(block, translated, encoded, policy=DEFAULT_POLICY):
    try:
        if encoded.root is not block or etree.tostring(block) != encoded.snapshot:
            return False
        try:
            fragment = parse_fragment(translated)
        except etree.XMLSyntaxError:
            return False
        if not valid_slots(fragment, encoded.slots, policy):
            return False
        return apply_decoded(block, fragment, encoded, policy)
    finally:
        encoded.close()


def in_skipped(element, policy=DEFAULT_POLICY):
    if element.get('translate') == 'no':
        return True
    for ancestor in element.iterancestors():
        if ancestor.tag.lower() in policy.opaque_tags or ancestor.get('translate') == 'no':
            return True
    return isinstance(element.tag, str) and element.tag.lower() in policy.opaque_tags


def block_units(body, policy=DEFAULT_POLICY):
    chosen, selected = [], set()
    for element in body.iter():
        if not isinstance(element.tag, str) or element.tag.lower() not in policy.block_tags:
            continue
        if in_skipped(element, policy):
            continue
        if any(ancestor in selected for ancestor in element.iterancestors()):
            continue
        chosen.append(element)
        selected.add(element)
    return chosen


def _outside_blocks(node, blocks, policy):
    return not in_skipped(node, policy) and not (
        node in blocks or any(ancestor in blocks for ancestor in node.iterancestors()))


def _loose_text(element, blocks, policy):
    return (isinstance(element.tag, str) and _outside_blocks(element, blocks, policy)
            and (element.text or '').strip() and element.tag.lower() not in policy.block_tags)


def _loose_tail(element, blocks, policy):
    parent = element.getparent()
    return (element.tail or '').strip() and parent is not None and _outside_blocks(parent, blocks, policy)


def loose_text_nodes(body, blocks, policy=DEFAULT_POLICY):
    block_set = set(blocks)
    found = []
    for element in body.iter():
        if _loose_text(element, block_set, policy):
            found.append((element, 'text'))
        if _loose_tail(element, block_set, policy):
            found.append((element, 'tail'))
    return found
