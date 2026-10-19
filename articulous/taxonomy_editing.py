"""Transactional XML tag corrections with caller-defined provenance semantics."""
from pathlib import Path
import lxml.etree as etree

from .source_transactions import source_transaction
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


def capture_documents(content, transaction, layout):
    trees = {}
    for path in sorted(content.glob(layout.pattern)):
        relative = path.relative_to(content)
        transaction.capture(relative)
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        trees[relative] = etree.parse(str(path), parser)
    return trees


def current_provenance(trees, transaction, provenance):
    current = {}
    if provenance is None:
        return current
    for relative, tree in trees.items():
        root = tree.getroot()
        source = root.findtext(provenance.source_element)
        if source:
            source_relative = provenance.source_reference(relative, source)
            if (source_relative in trees and root.findtext(provenance.hash_element)
                    == provenance.hash_fingerprint(transaction.capture(source_relative))):
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


def refresh_provenance(trees, current, transaction, provenance):
    refreshed = 0
    for relative, source_relative in current.items():
        tree = trees[relative]
        node = tree.getroot().find(provenance.hash_element)
        staged = transaction.stage / source_relative
        digest = staged.read_bytes() if staged.is_file() else None
        if digest is not None:
            from hashlib import sha256
            fingerprint = sha256(digest).digest()
        else:
            fingerprint = transaction.capture(source_relative)
        fresh = provenance.hash_fingerprint(fingerprint)
        if node.text != fresh:
            node.text = fresh
            stage_document(transaction, relative, tree)
            refreshed += 1
    return refreshed


def apply_map(content: Path, mapping, layout: TaxonomyLayout) -> TaxonomyEdits:
    validate_map(mapping)
    etree.Element(layout.tag_element)
    rewritten = 0
    with source_transaction(content) as transaction:
        trees = capture_documents(content, transaction, layout)
        current = current_provenance(trees, transaction, layout.provenance)
        for relative, tree in trees.items():
            if replace_tags(tree, mapping, layout.tag_element):
                stage_document(transaction, relative, tree)
                rewritten += 1
        refreshed = refresh_provenance(trees, current, transaction, layout.provenance)
    return TaxonomyEdits(rewritten, refreshed)
