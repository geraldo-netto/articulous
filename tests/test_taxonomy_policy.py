"""EDIT-002/TAG-003: schema, immutable policy and invalid-rule properties."""

import random
import unittest
from dataclasses import FrozenInstanceError


def raw_policy():
    return {"schema": 1, "removed": ["water"], "merged": {"shell-script": "shell"}}


class TagPolicyContract(unittest.TestCase):
    def test_tag003_valid_policy_is_independent_and_immutable(self):
        from articulous.taxonomy_policy import TagPolicy

        raw = raw_policy()
        policy = TagPolicy.from_mapping(raw)
        raw["removed"].clear()
        raw["merged"].clear()
        self.assertEqual(frozenset({"water"}), policy.removed)
        self.assertEqual({"shell-script": "shell"}, dict(policy.merged))
        with self.assertRaises(TypeError):
            mutate_mapping(policy.merged)
        with self.assertRaises(FrozenInstanceError):
            setattr(policy, "removed", frozenset())
        self.assertIsNone(
            policy.validate(["", "shell", "useful", "x" * 4096], "fixture")
        )
        self.assertIsNone(
            TagPolicy.from_mapping({"schema": 1, "removed": [], "merged": {}}).validate(
                [], "empty"
            )
        )

    def test_tag003_rejects_invalid_schema_and_fields(self):
        from articulous.taxonomy_policy import TagPolicy

        for value in (
            None,
            False,
            [],
            "",
            {},
            {"schema": 1},
            dict(raw_policy(), extra=True),
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(value)
        for value in (None, False, True, 0, 2, -1, 1.0, "1", 2**100):
            with (
                self.subTest(schema=value),
                self.assertRaisesRegex(ValueError, "schema"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), schema=value))

    def test_tag003_rejects_invalid_rule_containers_and_duplicates(self):
        from articulous.taxonomy_policy import TagPolicy

        for value in (None, False, "", {}, ("water",), ["water", "water"]):
            with (
                self.subTest(removed=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), removed=value))
        for value in (None, False, "", [], [("old", "new")]):
            with (
                self.subTest(merged=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), merged=value))

    def test_tag003_rejects_conflicting_targets_chains_and_cycles(self):
        from articulous.taxonomy_policy import TagPolicy

        for merged in (
            {"water": "shell"},
            {"shell-script": "water"},
            {"shell-script": "shell-script"},
            {"a": "b", "b": "c"},
            {"a": "b", "b": "a"},
        ):
            with (
                self.subTest(merged=merged),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), merged=merged))

    def test_tag003_bounded_invalid_slugs_are_rejected_at_every_boundary(self):
        from articulous.taxonomy_policy import TagPolicy

        generator = random.Random(3)
        invalid = [
            None,
            True,
            0,
            -1,
            2**100,
            [],
            {},
            "",
            "UPPER",
            "-a",
            "a-",
            "a--b",
            "日本語",
        ]
        invalid += [
            "tag" + generator.choice("/._ #?\n\x00") + str(index) for index in range(64)
        ]
        for value in invalid:
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), removed=[value]))
        for value in ("", "../tag", "tag/name", "UPPER"):
            with (
                self.subTest(target=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                TagPolicy.from_mapping(dict(raw_policy(), merged={"old": value}))
        policy = TagPolicy.from_mapping(raw_policy())
        for value in invalid:
            if value == "":
                continue
            with (
                self.subTest(input=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                policy.validate([value], "fixture")

    def test_tag003_validation_names_the_required_source_change(self):
        from articulous.taxonomy_policy import TagPolicy

        policy = TagPolicy.from_mapping(raw_policy())
        with self.assertRaisesRegex(ValueError, "water.*removed"):
            policy.validate(["shell", "water"], "fixture.xml")
        with self.assertRaisesRegex(ValueError, "shell-script.*use 'shell'"):
            policy.validate(["shell-script"], "fixture.xml")

    def test_tag003_scalar_inputs_cannot_bypass_the_tag_collection_contract(self):
        from articulous.taxonomy_policy import TagPolicy

        policy = TagPolicy.from_mapping(raw_policy())
        for value in ("water", b"water", None, False, 0, float("nan")):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "TAG-003"),
            ):
                policy.validate(value, "fixture.xml")


def mutate_mapping(mapping):
    mapping["other"] = "shell"
