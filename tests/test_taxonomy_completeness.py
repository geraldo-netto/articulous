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
