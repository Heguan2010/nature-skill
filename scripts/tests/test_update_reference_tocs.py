from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "update-reference-tocs.py"
SPEC = importlib.util.spec_from_file_location("update_reference_tocs", SCRIPT)
assert SPEC and SPEC.loader
TOCS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOCS
SPEC.loader.exec_module(TOCS)


class GithubAnchorTests(unittest.TestCase):
    def test_spaces_around_a_hyphen_are_not_collapsed(self) -> None:
        self.assertEqual(TOCS.github_anchor("Input - Output", {}), "input---output")

    def test_removed_punctuation_leaves_adjacent_hyphens(self) -> None:
        self.assertEqual(TOCS.github_anchor("A & B", {}), "a--b")

    def test_plain_heading_and_duplicates(self) -> None:
        seen: dict[str, int] = {}
        self.assertEqual(TOCS.github_anchor("Grounding checks", seen), "grounding-checks")
        self.assertEqual(TOCS.github_anchor("Grounding checks", seen), "grounding-checks-1")

    def test_code_and_links_are_cleaned_first(self) -> None:
        self.assertEqual(TOCS.github_anchor("Use `x` and [docs](http://a.b)", {}), "use-x-and-docs")


if __name__ == "__main__":
    unittest.main()
