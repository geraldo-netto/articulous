"""Optional XML mirror adapter; layouts, prompts and link policy are caller-owned."""
import io
import lxml.etree as etree
from .markup import block_units, encode_block, decode_block, loose_text_nodes, in_skipped
from .source_files import replace_file
from .source_transactions import fingerprint
from .translation_contracts import XmlTranslationLayout


def translate_blocks(blocks, translator, source, target, stats, policy, log):
    for block in blocks:
        encoded = encode_block(block, policy=policy)
        if not encoded.text.strip():
            encoded.close()
            continue
        try:
            result = translator.translate(encoded.text, source, target)
            stats['units'] += 1
            if result is None or not decode_block(block, result, encoded, policy=policy):
                stats['failed'] += 1
                log(f'    ! kept source for a <{block.tag}> unit')
        finally:
            encoded.close()


def translate_loose(body, blocks, translator, source, target, stats, policy, log):
    for element, kind in loose_text_nodes(body, blocks, policy=policy):
        original = getattr(element, kind)
        result = translator.translate(original, source, target, keep_placeholders=False)
        stats['units'] += 1
        if result is None:
            stats['failed'] += 1
            continue
        leading = original[:len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()):]
        setattr(element, kind, leading + result.strip() + trailing)


def translate_attributes(body, translator, source, target, stats, policy, log):
    for element in body.iter():
        if not isinstance(element.tag, str) or in_skipped(element, policy=policy):
            continue
        for name in policy.translatable_attributes:
            value = element.get(name)
            if value and value.strip():
                result = translator.translate(value, source, target, keep_placeholders=False)
                stats['units'] += 1
                if result is not None:
                    element.set(name, result)
                else:
                    stats['failed'] += 1




def translate_body(body, translator, source, target, stats, policy, log):
    blocks = block_units(body, policy=policy)
    translate_blocks(blocks, translator, source, target, stats, policy, log)
    translate_loose(body, blocks, translator, source, target, stats, policy, log)
    translate_attributes(body, translator, source, target, stats, policy, log)


def set_field(root, name, value, attributes):
    if attributes:
        root.set(name, value)
    else:
        old = root.find(name)
        if old is None:
            old = etree.SubElement(root, name)
        old.text = value


def translate_metadata(root, layout, translator, source, target, stats):
    for name in layout.prose_fields:
        value = root.get(name) if layout.metadata_attributes else root.findtext(name)
        if value and value.strip():
            result = translator.translate(value, source, target, keep_placeholders=False)
            stats['units'] += 1
            if result is not None:
                set_field(root, name, result, layout.metadata_attributes)
            else:
                stats['failed'] += 1


def clear_hash(root, name):
    root.attrib.pop(name, None)
    for inherited in root.findall(name):
        root.remove(inherited)


def translate_links(body, policy, rewrite):
    if rewrite is None:
        return
    for link in body.iter('a'):
        href = link.get('href')
        if href and not in_skipped(link, policy):
            link.set('href', rewrite(href))


def stamp_provenance(root, layout, source, model, digest):
    markers = [(layout.source_element, source), (layout.generator_element, model)]
    if digest is not None:
        markers.append((layout.hash_element, digest))
    for name, value in markers:
        set_field(root, name, value, layout.provenance_attributes)


def write_translation(tree, source, snapshot, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    def write(path):
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        if source.read_bytes() != snapshot:
            raise ValueError(f'Translation source changed: {source}')
        if fingerprint(target) != expected:
            raise ValueError(f'Translation target changed: {target}')
    replace_file(target, write)


def mirror_xml(source_path, target_path, source_language, target_language, translator, stats,
               layout: XmlTranslationLayout, policy, log, *, rewrite_link=None):
    before = stats['failed']
    expected = fingerprint(target_path)
    snapshot = source_path.read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(io.BytesIO(snapshot), parser)
    root = tree.getroot()
    clear_hash(root, layout.hash_element)
    translate_metadata(root, layout, translator, source_language, target_language, stats)
    if layout.language_element is not None:
        node = root.find(layout.language_element)
        if node is not None:
            node.text = target_language
    body = root.find(layout.body_element)
    if body is not None:
        translate_body(body, translator, source_language, target_language, stats, policy, log)
        translate_links(body, policy, rewrite_link)
    if source_path.read_bytes() != snapshot:
        raise ValueError(f'Translation source changed: {source_path}')
    digest = layout.digest(snapshot) if stats['failed'] == before else None
    stamp_provenance(root, layout, source_language, translator.model, digest)
    write_translation(tree, source_path, snapshot, target_path, expected)
