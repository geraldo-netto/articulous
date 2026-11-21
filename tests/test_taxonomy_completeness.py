"""EDIT-002/TAG-007: optional literal completeness policy."""

from dataclasses import FrozenInstanceError, replace
import random
import unittest


class TagCompleteness(unittest.TestCase):
    def test_tag007_whole_words_phrases_and_translation_union(self):
        from articulous.taxonomy_completeness import TagSummary, missing_tags

        records = [
            TagSummary(
                "vocabulary", "vocab", "", "", ("linux", "java", "command-line", "c")
            ),
            TagSummary("tv", "en/tv", "LINUX television", "", ("tv",)),
            TagSummary("tv", "it/tv", "Televisore", "", ("tv",)),
            TagSummary("shell", "shell", "Use the command line", "", ("shell",)),
            TagSummary(
                "negative",
                "negative",
                "JavaScript xlinux linux2 _linux",
                "",
                ("other",),
            ),
            TagSummary("audio", "audio", "C-media adapter", "", ("audio",)),
        ]
        self.assertEqual(
            {
                "en/tv": ("linux",),
                "it/tv": ("linux",),
                "shell": ("command-line",),
                "audio": ("c",),
            },
            missing_tags(records),
        )
        complete = records + [TagSummary("tv", "pt/tv", "", "", ("linux", "tv"))]
        self.assertEqual(("linux",), missing_tags(complete)["it/tv"])
        self.assertEqual({}, missing_tags([]))

    def test_tag007_literals_are_escaped_and_fields_do_not_form_phrases(self):
        from articulous.taxonomy_completeness import TagSummary, missing_tags

        records = [
            TagSummary(
                "vocabulary", "vocab", "", "", ("c++", "node.js", "command-line")
            ),
            TagSummary("literal", "literal", "C++ and NODE.JS", "", ("other",)),
            TagSummary("negative", "negative", "nodeXjs command", "line", ("other",)),
        ]
        self.assertEqual({"literal": ("c++", "node.js")}, missing_tags(records))

    def test_tag007_rejects_invalid_inputs_and_keeps_metadata_immutable(self):
        from articulous.taxonomy_completeness import TagSummary, missing_tags

        valid = TagSummary("one", "en/one", "", "", ("linux",))
        for field in ("key", "source", "title", "description"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(valid, **{field: None})
        for field in ("key", "source"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(valid, **{field: " "})
        for tags in (None, "linux", ["linux"], (None,), ("",), (" ",)):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                replace(valid, tags=tags)
        with self.assertRaises(FrozenInstanceError):
            setattr(valid, "tags", ("other",))
        for records in (
            None,
            False,
            0,
            "",
            b"",
            {},
            "linux",
            [None],
            [False],
            [valid, valid],
        ):
            with self.subTest(records=records), self.assertRaises(ValueError):
                missing_tags(records)

    def test_tag007_bounded_word_boundaries_do_not_match_embedded_tokens(self):
        from articulous.taxonomy_completeness import TagSummary, missing_tags

        generator = random.Random(7)
        for index in range(64):
            prefix = generator.choice(("x", "_", "7", "é"))
            records = [
                TagSummary("vocab", "vocab", "", "", ("linux",)),
                TagSummary("post", "post", prefix + "linux", "linux" + prefix, ()),
            ]
            with self.subTest(index=index):
                self.assertEqual({}, missing_tags(records))
                self.assertEqual(
                    {"post": ("linux",)},
                    missing_tags([records[0], replace(records[1], title="(Linux)")]),
                )


def _full_scan_missing(records):
    from articulous.taxonomy_completeness import required_tags, summary_groups, tag_pattern

    patterns = {tag: tag_pattern(tag) for row in records for tag in row.tags}
    result = {}
    for group in summary_groups(records).values():
        expected = required_tags(group, patterns)
        for row in group:
            if names := tuple(sorted(expected.difference(row.tags))):
                result[row.source] = names
    return result


def test_review28_52_sparse_vocabulary_checks_only_matching_anchors(monkeypatch):
    from articulous import taxonomy_completeness as taxonomy

    tags = tuple(f'topic{number}-policy' for number in range(200))
    rows = [taxonomy.TagSummary('vocabulary', 'vocab', '', '', tags)]
    for number in range(1000):
        title = f'Notes on TOPIC{number % len(tags)} policy'
        rows.append(taxonomy.TagSummary(str(number // 2), str(number), title, 'Ordinary release notes.', ()))
    expected = _full_scan_missing(rows)
    searches = 0
    compile_pattern = taxonomy.tag_pattern

    class CountedPattern:
        def __init__(self, name):
            self.pattern = compile_pattern(name)

        def search(self, text):
            nonlocal searches
            searches += 1
            return self.pattern.search(text)

    monkeypatch.setattr(taxonomy, 'tag_pattern', CountedPattern)
    assert taxonomy.missing_tags(rows) == expected
    assert 0 < searches <= 1000


def test_review28_52_unicode_and_punctuation_match_full_scan():
    from articulous.taxonomy_completeness import TagSummary, missing_tags

    tags = ('i', 's', 'k', 'silk', 'C++', '.NET', '#tag', 'x_y', 'node.js', '--', '-foo',
            'quite--long phrase', 'C#', 'κι', 'ẞ', 'ﬀ', '東京都', 'İşte', 'ZÉ', '---end--',
            '_double', '+', '\u0301', 'A+B', 'node.JS', 'A  b', 'foo')
    tokens = tags + ('İ', 'ı', 'ſ', 'K', 'ſİLK', 'Kind', 'SS', 'FF', 'a+b', 'quite\tlong-phrase',
                     '東京都庁', '日本x_y', 'ı_foo', 'x\u0301s', 'node', 'js', '-END-', 'long', '')
    rows = [TagSummary('vocab', 'vocab', '', '', tags)]
    rng = random.Random(2852)
    for number in range(256):
        join = rng.choice(('', ' ', '-', '.', '\u0301', '\n', '\u2003', '—'))
        text = join.join(rng.choices(tokens, k=6))
        rows.append(TagSummary(str(number // 3), str(number), text, rng.choice(tokens), ()))
    expected = _full_scan_missing(rows)
    assert list(missing_tags(rows).items()) == list(expected.items())


def test_review28_52_every_unicode_codepoint_matching_an_ascii_word_character():
    import re
    import string
    import sys

    from articulous.taxonomy_completeness import TagSummary, missing_tags

    alphabet = tuple(string.ascii_lowercase + string.digits + '_')
    equivalent = re.compile('[a-z0-9_]', re.IGNORECASE).fullmatch
    characters = (chr(code) for code in range(128, sys.maxunicode + 1))
    rows = [TagSummary('vocab', 'vocab', '', '', alphabet)]
    rows.extend(TagSummary(char, char, char, '', ()) for char in characters if equivalent(char))
    assert list(missing_tags(rows).items()) == list(_full_scan_missing(rows).items())


def test_review28_52_custom_patterns_remain_independent_of_tag_spelling():
    import re
    from articulous.taxonomy_completeness import TagSummary, required_tags

    fields = [TagSummary('a', 'one', 'match', '', ('assigned',))]
    assert required_tags(fields, {'alias': re.compile('match'), 'empty': re.compile('^$')}) == {
        'alias', 'empty', 'assigned',
    }


def test_review28_52_unindexed_vocabulary_and_empty_vocabulary():
    from articulous.taxonomy_completeness import TagSummary, missing_tags

    row = TagSummary('post', 'one', 'CUDA then C++: 東 京 +', '', ())
    assert missing_tags([row]) == {}
    vocab = TagSummary('vocab', 'terms', '', '', ('+', '東 京'))
    assert missing_tags([vocab, row]) == {'one': ('+', '東 京')}
