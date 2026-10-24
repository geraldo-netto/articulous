"""EDIT-002/REV-053/054/111: atomic corrections and truthful provenance."""

from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import lxml.etree as etree
import pytest
from articulous.taxonomy_contracts import ProvenanceLayout, TaxonomyLayout
from articulous.taxonomy_editing import apply_map


def source_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def source_reference(relative, language):
    return Path(language) / relative.name


def digest(value):
    return value.hex()[:16]


class TagMapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.content = Path(temporary.name) / "content"
        for lang in ("en", "es", "it", "pt"):
            for name, tag in [("a", "alpha"), ("b", "beta")]:
                path = self.content / lang / f"{name}.xml"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"<article><lang>{lang}</lang><tag>{tag}</tag>"
                    "<tag>drop</tag><body><p>Prose</p></body></article>"
                )

    def snapshot(self):
        return {
            p.relative_to(self.content): p.read_bytes()
            for p in self.content.rglob("*.xml")
        }

    def apply(self, mapping):
        with redirect_stdout(io.StringIO()):
            apply_map(
                self.content,
                mapping,
                TaxonomyLayout(
                    "tag",
                    "*/*.xml",
                    ProvenanceLayout(
                        "translated-from", "source-hash", source_reference, digest
                    ),
                ),
            )

    def test_rev053_invalid_maps_reject_before_any_write(self):
        # Bounded invalid types, including values after an otherwise valid edit.
        maps = [None, [], "alpha", 0, False]
        for invalid in (0, 42, -1, 1.5, False, True, [], {}, ["new"]):
            maps.append({"alpha": "new", "beta": invalid})
            try:
                maps.append(key_map(invalid))
            except TypeError:
                pass
        maps += [{"alpha": "new", "beta": "\x00"}, {"\ud800": "new"}]
        before = self.snapshot()
        for mapping in maps:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    self.apply(mapping)
                self.assertEqual(before, self.snapshot())

    def test_rev053_late_parse_failure_leaves_all_files_unchanged(self):
        (self.content / "pt/b.xml").write_text("<article>")
        before = self.snapshot()
        with self.assertRaises(etree.XMLSyntaxError):
            self.apply({"alpha": "new", "beta": "new"})
        self.assertEqual(before, self.snapshot())

    def test_rev053_late_stage_failure_leaves_all_files_unchanged(self):
        before = self.snapshot()
        real_write = Path.write_bytes

        def write(path, data):
            if path.parts[-2:] == ("pt", "b.xml"):
                raise OSError("injected stage failure")
            return real_write(path, data)

        with patch.object(Path, "write_bytes", write):
            with self.assertRaisesRegex(OSError, "injected stage failure"):
                self.apply({"alpha": "new", "beta": "new"})
        self.assertEqual(before, self.snapshot())

    def test_rev053_late_publish_failure_rolls_back_all_files(self):
        before = self.snapshot()
        real_replace = Path.replace

        def replace(path, target):
            if "new" in path.parts and Path(target) == self.content / "pt/b.xml":
                raise OSError("injected publication failure")
            return real_replace(path, target)

        with patch.object(Path, "replace", replace):
            with self.assertRaisesRegex(OSError, "injected publication failure"):
                self.apply({"alpha": "new", "beta": "new"})
        self.assertEqual(before, self.snapshot())

    def test_rev053_multilingual_merge_drop_and_noop(self):
        self.apply({"alpha": "new", "beta": "new", "drop": None})
        for path in self.content.rglob("*.xml"):
            self.assertEqual(["new"], etree.parse(str(path)).xpath("//tag/text()"))
        before = self.snapshot()
        stats = {p: p.stat() for p in self.content.rglob("*.xml")}
        self.apply({"new": "new"})
        self.assertEqual(before, self.snapshot())
        for path, old in stats.items():
            self.assertEqual(
                (old.st_ino, old.st_mtime_ns),
                (path.stat().st_ino, path.stat().st_mtime_ns),
            )

    def test_rev053_empty_strings_and_unicode_keep_existing_map_contract(self):
        self.apply({"alpha": "日本語", "beta": "", "drop": "日本語"})
        for path in self.content.rglob("*.xml"):
            self.assertEqual(["日本語"], etree.parse(str(path)).xpath("//tag/text()"))

    def test_rev053_provenance_is_published_with_tags(self):
        source = self.content / "en/a.xml"
        target = self.content / "es/a.xml"
        tree = etree.parse(str(target))
        etree.SubElement(tree.getroot(), "translated-from").text = "en"
        etree.SubElement(tree.getroot(), "source-hash").text = source_hash(source)
        tree.write(str(target))
        (self.content / "pt/empty.xml").write_text("<article><body/></article>")
        self.apply({"alpha": "new", "drop": None})
        root = etree.parse(str(target)).getroot()
        self.assertEqual(["new"], [n.text for n in root.findall("tag")])
        self.assertEqual(source_hash(source), root.findtext("source-hash"))

    def test_rev054_only_previously_current_hashes_advance(self):
        maps = [
            {},
            {"unrelated": "new"},
            {"alpha": "alpha"},
            {"alpha": "new"},
            {"target-only": "new"},
            {"drop": None},
        ]
        for state in ("current", "stale", "missing", "empty"):
            for mapping in maps:
                with self.subTest(state=state, mapping=mapping):
                    self._check_hash_case(state, mapping)

    def _prepare_hash_case(self, state):
        self.setUp()
        source = self.content / "en/a.xml"
        target = self.content / "es/a.xml"
        tree = etree.parse(str(target))
        etree.SubElement(tree.getroot(), "tag").text = "target-only"
        etree.SubElement(tree.getroot(), "translated-from").text = "en"
        old_hash = None if state in ("missing", "empty") else source_hash(source)
        if state != "missing":
            etree.SubElement(tree.getroot(), "source-hash").text = old_hash
        tree.write(str(target))
        if state == "stale":
            source.write_bytes(source.read_bytes().replace(b"Prose", b"Changed source prose"))
        return source, target, old_hash

    def _check_hash_case(self, state, mapping):
        source, target, old_hash = self._prepare_hash_case(state)
        before = self.snapshot()
        self.apply(mapping)
        root = etree.parse(str(target)).getroot()
        expected = source_hash(source) if state == "current" else ("" if state == "empty" else old_hash)
        self.assertEqual(expected, root.findtext("source-hash"))
        if state != "current":
            self.assertNotEqual(source_hash(source), root.findtext("source-hash"))
        if not mapping or "unrelated" in mapping or mapping == {"alpha": "alpha"}:
            self.assertEqual(before, self.snapshot())

    def test_rev054_missing_source_keeps_provenance_stale(self):
        target = self.content / "es/a.xml"
        tree = etree.parse(str(target))
        etree.SubElement(tree.getroot(), "translated-from").text = "absent"
        etree.SubElement(tree.getroot(), "source-hash").text = "stale"
        tree.write(str(target))
        self.apply({"alpha": "new"})
        root = etree.parse(str(target)).getroot()
        self.assertEqual("stale", root.findtext("source-hash"))
        self.assertEqual("new", root.findtext("tag"))

    def test_rev111_changed_read_only_source_aborts_target_only_map(self):
        from articulous.source_transactions import SourceTransaction

        source = self.content / "en/a.xml"
        target = self.content / "es/a.xml"
        tree = etree.parse(str(target))
        root = tree.getroot()
        etree.SubElement(root, "tag").text = "target-only"
        etree.SubElement(root, "translated-from").text = "en"
        etree.SubElement(root, "source-hash").text = source_hash(source)
        tree.write(str(target))
        before = target.read_bytes()
        publish = SourceTransaction.publish

        def concurrent_edit(transaction):
            source.write_bytes(source.read_bytes().replace(b"Prose", b"Owner edit"))
            return publish(transaction)

        with patch.object(SourceTransaction, "publish", concurrent_edit):
            with self.assertRaisesRegex(ValueError, "changed during staging"):
                self.apply({"target-only": "renamed"})
        self.assertEqual(before, target.read_bytes())
        self.assertIn(b"Owner edit", source.read_bytes())


class NeutralLayout(unittest.TestCase):
    def test_edit002_neutral_schema_without_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.xml").write_text(
                "<entry><topic>Old</topic><topic>Keep</topic></entry>"
            )
            result = apply_map(root, {"Old": "New"}, TaxonomyLayout("topic", "*.xml"))
            self.assertEqual((1, 0), (result.rewritten, result.refreshed))
            self.assertEqual(
                ["New", "Keep"],
                etree.parse(str(root / "entry.xml")).xpath("//topic/text()"),
            )


def key_map(value):
    return {value: "new"}


def provenance_document(root, language, source=None, source_digest=None):
    path = root / language / 'item.xml'
    path.parent.mkdir(exist_ok=True)
    article = etree.Element('article')
    etree.SubElement(article, 'tag').text = 'old'
    if source is not None:
        etree.SubElement(article, 'translated-from').text = source
        etree.SubElement(article, 'source-hash').text = source_digest
    path.write_bytes(etree.tostring(article))
    return path


def provenance_layout(project=digest):
    return TaxonomyLayout('tag', '*/*.xml', ProvenanceLayout(
        'translated-from', 'source-hash', source_reference, project))


@pytest.fixture
def provenance_root(tmp_path):
    root = tmp_path / 'content'
    root.mkdir()
    return root


@pytest.mark.parametrize('languages', [('a', 'y', 'z'), ('z', 'y', 'a')])
def test_review002_dependency_order_refreshes_final_source_bytes(provenance_root, languages):
    tmp_path = provenance_root
    first, middle, last = languages
    source = provenance_document(tmp_path, last)
    translated = provenance_document(tmp_path, middle, last, source_hash(source))
    leaf = provenance_document(tmp_path, first, middle, source_hash(translated))
    stale = provenance_document(tmp_path, 'stale', middle, 'stale-hash')
    edits = apply_map(tmp_path, {'old': 'new'}, provenance_layout())
    assert (edits.rewritten, edits.refreshed) == (4, 2)
    assert etree.parse(str(leaf)).findtext('source-hash') == source_hash(translated)
    assert etree.parse(str(translated)).findtext('source-hash') == source_hash(source)
    assert etree.parse(str(stale)).findtext('source-hash') == 'stale-hash'
    assert not list(tmp_path.parent.glob('.articulous-edit-*'))


@pytest.mark.parametrize('links', [{'a': 'a'}, {'a': 'b', 'b': 'a'}])
def test_review002_cycles_reject_without_publication(provenance_root, links):
    tmp_path = provenance_root
    for language, source in links.items():
        provenance_document(tmp_path, language, source, 'current')
    before = {path: path.read_bytes() for path in tmp_path.rglob('*.xml')}
    with pytest.raises(ValueError, match='cycle'):
        apply_map(tmp_path, {'old': 'new'}, provenance_layout(lambda _: 'current'))
    assert {path: path.read_bytes() for path in before} == before
    assert not list(tmp_path.parent.glob('.articulous-edit-*'))
