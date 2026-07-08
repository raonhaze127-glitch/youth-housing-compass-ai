from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "sync_notion.py"
)
SPEC = importlib.util.spec_from_file_location("sync_notion", SCRIPT_PATH)
assert SPEC and SPEC.loader
sync_notion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_notion)


class SyncNotionStatusTests(unittest.TestCase):
    def test_closed_application_status_is_not_reopened_as_unknown(self) -> None:
        properties = {
            "청약상태": {"select": {"name": "일정확인"}},
            "청약정렬": {"number": 2},
        }
        existing_page = {
            "properties": {
                "청약상태": {
                    "type": "select",
                    "select": {"name": "마감"},
                }
            }
        }

        sync_notion._preserve_closed_application_status(properties, existing_page)

        self.assertEqual(properties["청약상태"]["select"]["name"], "마감")
        self.assertEqual(properties["청약정렬"]["number"], 9)

    def test_closed_application_status_allows_confirmed_future_schedule(self) -> None:
        properties = {
            "청약상태": {"select": {"name": "모집예정"}},
            "청약정렬": {"number": 1},
        }
        existing_page = {
            "properties": {
                "청약상태": {
                    "type": "select",
                    "select": {"name": "마감"},
                }
            }
        }

        sync_notion._preserve_closed_application_status(properties, existing_page)

        self.assertEqual(properties["청약상태"]["select"]["name"], "모집예정")
        self.assertEqual(properties["청약정렬"]["number"], 1)


if __name__ == "__main__":
    unittest.main()
