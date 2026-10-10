"""Execute the public handoff migration examples without optional SDKs."""

import doctest
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReleaseGuidanceTests(unittest.TestCase):
    def test_legacy_and_current_xml_counter_migration_examples(self):
        failures, attempted = doctest.testfile(
            str(ROOT / "docs" / "editor-handoff.md"), module_relative=False,
            encoding="utf-8", optionflags=doctest.ELLIPSIS)
        self.assertGreater(attempted, 0, "The handoff migration guide needs executable examples")
        self.assertEqual(failures, 0)


if __name__ == "__main__":
    unittest.main()
