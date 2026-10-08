import re
import unittest
from pathlib import Path

from heritage_matching import load_matching_rules
from heritage_relations import name_relation


DIALOG = Path(__file__).with_name("arch_distribution_dialog.py")
EXPECTED = {
    "=": {"equal", "alias", "affix_omitted"},
    "⊂": {"left_specific"},
    "≠": {"designator_conflict", "sibling", "unrelated"},
}


def help_example_pairs():
    """Yield ``(left, operator, right)`` from the name-relation help tables."""
    source = DIALOG.read_text(encoding="utf-8")
    start = source.index("def _matching_rules_help_html")
    end = source.index("def show_matching_rules_help")
    for cell in re.findall(r"<td>([^<]*(?:<br>[^<]*)*)</td>", source[start:end]):
        for pair in cell.split("<br>"):
            match = re.match(r"\s*(.+?)\s+([=⊂≠])\s+(.+?)\s*$", pair)
            if match:
                yield match.groups()


class HelpExampleTests(unittest.TestCase):
    def test_every_help_example_matches_the_classifier(self):
        rules = load_matching_rules()
        pairs = list(help_example_pairs())
        self.assertGreaterEqual(len(pairs), 10)
        for left, operator, right in pairs:
            with self.subTest(pair=f"{left} {operator} {right}"):
                self.assertIn(
                    name_relation(left, right, rules), EXPECTED[operator]
                )


if __name__ == "__main__":
    unittest.main()
