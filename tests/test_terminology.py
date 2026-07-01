"""Guard the user-facing "Condition Group" terminology (formerly "Breed").

These checks read source/doc text rather than launching the GUI, so they stay
stable in headless environments. Internal compatibility names (``breed``,
``BreedSummaryRow``, ``last_import_breed``, the ``breed`` metadata key, etc.)
are intentionally left untouched and are not asserted against here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class UserFacingTerminologyTests(unittest.TestCase):
    def test_gui_has_no_user_facing_breed_labels(self) -> None:
        src = _read("actintrack_app/gui.py")
        # The workspace tree and dialog text must not expose "Breed".
        self.assertNotIn('"Breed:"', src)
        self.assertNotIn("this Breed?", src)
        self.assertIn("Condition Group", src)
        self.assertIn("this Condition Group?", src)
        self.assertIn("tree_samples", src)
        self.assertNotIn("Full Sample Preview — orient the data", src)
        self.assertNotIn('"◀ Prev"', src)
        self.assertNotIn('"Next ▶"', src)
        self.assertNotIn("btn_refresh_samples", src)
        self.assertIn("Refresh Explorer", src)
        self.assertIn("_LEFT_PANEL_MIN_WIDTH", src)
        self.assertIn("setCollapsible", src)

    def test_analysis_view_headers_use_condition_group(self) -> None:
        src = _read("actintrack_app/analysis_view.py")
        self.assertNotIn("Breed Summary", src)
        self.assertNotIn("Breed Comparison", src)
        self.assertIn("Condition Group Summary", src)
        self.assertIn("Condition Group Comparison", src)
        self.assertIn('"Condition Group"', src)

    def test_menu_and_purge_labels_use_condition_group(self) -> None:
        menus = _read("actintrack_app/gui_menus.py")
        self.assertNotIn('"Breed:"', menus)
        self.assertIn('"Condition Group:"', menus)

        purge = _read("actintrack_app/purge_cleanup_dialog.py")
        self.assertNotIn("Breed Annotations Only", purge)
        self.assertNotIn("Complete Breed Purge", purge)
        self.assertIn("Condition Group Annotations Only", purge)
        self.assertIn("Complete Condition Group Purge", purge)

    def test_readme_uses_condition_group(self) -> None:
        readme = _read("README.md")
        # No capitalized user-facing "Breed" token should remain.
        self.assertNotIn("**Breed**", readme)
        self.assertNotIn("by Breed", readme)
        self.assertIn("Condition Group", readme)

    def test_user_doc_uses_condition_group(self) -> None:
        doc = _read("ActinTrackCV_User_Documentation_Refined.md")
        self.assertIn("Condition Group", doc)
        # The legacy-terminology note still records the old name as legacy.
        self.assertIn("| Breed | Condition Group |", doc)


if __name__ == "__main__":
    unittest.main()
