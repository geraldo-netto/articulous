"""Transactional XML tag corrections with caller-defined provenance semantics."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from graphlib import TopologicalSorter
import lxml.etree as etree

from .filesystem import open_regular_file
from .source_transactions import fingerprint, source_transaction
from .taxonomy_contracts import TaxonomyEdits, TaxonomyLayout


def validate_map(mapping):
    if not isinstance(mapping, dict):
        raise ValueError('Tag map must be an object with string keys and string/null values')
    for key, value in mapping.items():
        if not isinstance(key, str) or (value is not None and not isinstance(value, str)):
            raise ValueError('Tag map must have string keys and string/null values')
        for text in (key, value):
            try:
                etree.Element('tag').text = text
            except (ValueError, UnicodeError) as error:
                raise ValueError('Tag map contains text invalid in XML') from error


def _read_document(path, expected):
    with open_regular_file(path) as source:
        content = source.read()
    if sha256(content).digest() != expected:
        raise ValueError(f'Import destination changed during staging: {path}')
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.parse(BytesIO(content), parser, base_url=str(path))


def _provenance_fields(tree, provenance):
    if provenance is None:
        return None, None
    root = tree.getroot()
    return root.findtext(provenance.source_element), root.findtext(provenance.hash_element)


def _stage_edits(content, transaction, layout, mapping):
    metadata = {}
    rewritten = 0
    for path in sorted(content.glob(layout.pattern)):
        relative = path.relative_to(content)
        expected = transaction.capture(relative)
        tree = _read_document(path, expected)
        metadata[relative] = _provenance_fields(tree, layout.provenance)
        if replace_tags(tree, mapping, layout.tag_element):
            stage_document(transaction, relative, tree)
            rewritten += 1
        del tree
    return metadata, rewritten


def _current_provenance(metadata, transaction, provenance):
    current = {}
    if provenance is None:
        return current
    for relative, (source, recorded) in metadata.items():
        if source:
            source_relative = provenance.source_reference(relative, source)
            if (source_relative in metadata
                    and recorded == provenance.hash_fingerprint(transaction.capture(source_relative))):
                current[relative] = source_relative
    return current


def replace_tags(tree, mapping, tag_element):
    root = tree.getroot()
    nodes = root.findall(tag_element)
    if not nodes:
        return False
    before = [node.text for node in nodes]
    after = list(dict.fromkeys(tag for tag in (mapping.get(tag, tag) for tag in before) if tag))
    if after == before:
        return False
    index = list(root).index(nodes[0])
    for node in nodes:
        root.remove(node)
    for offset, value in enumerate(after):
        node = etree.Element(tag_element)
        node.text = value
        root.insert(index + offset, node)
    return True


def stage_document(transaction, relative, tree):
    transaction.write(relative, etree.tostring(tree, encoding='utf-8', xml_declaration=True), force=True)


def _staged_generation(transaction, relative):
    staged = transaction.stage / relative
    digest = fingerprint(staged)
    if digest is not None:
        return staged, digest
    return transaction.destination(relative), transaction.capture(relative)


def _refresh_document(transaction, relative, source_relative, provenance):
    _, source_digest = _staged_generation(transaction, source_relative)
    fresh = provenance.hash_fingerprint(source_digest)
    path, expected = _staged_generation(transaction, relative)
    tree = _read_document(path, expected)
    node = tree.getroot().find(provenance.hash_element)
    if node.text == fresh:
        return False
    node.text = fresh
    stage_document(transaction, relative, tree)
    return True


def _refresh_provenance(current, transaction, provenance):
    refreshed = 0
    dependencies = {relative: (source,) for relative, source in current.items()}
    for relative in TopologicalSorter(dependencies).static_order():
        if relative in current and _refresh_document(transaction, relative, current[relative], provenance):
            refreshed += 1
    return refreshed


def apply_map(content: Path, mapping, layout: TaxonomyLayout) -> TaxonomyEdits:
    validate_map(mapping)
    etree.Element(layout.tag_element)
    with source_transaction(content) as transaction:
        metadata, rewritten = _stage_edits(content, transaction, layout, mapping)
        current = _current_provenance(metadata, transaction, layout.provenance)
        refreshed = _refresh_provenance(current, transaction, layout.provenance)
    return TaxonomyEdits(rewritten, refreshed)
