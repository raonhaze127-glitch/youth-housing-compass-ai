from datetime import date
import unittest

from app.status import calculate_status, normalize_date


class StatusTests(unittest.TestCase):
    def test_normalize_compact_date(self):
        self.assertEqual(normalize_date("20260619"), "2026-06-19")

    def test_open_is_inclusive(self):
        self.assertEqual(
            calculate_status("2026-06-01", "2026-06-19", date(2026, 6, 19)),
            "open",
        )

    def test_planned(self):
        self.assertEqual(
            calculate_status("2026-06-20", "2026-07-01", date(2026, 6, 19)),
            "planned",
        )

    def test_closed(self):
        self.assertEqual(
            calculate_status("2025-06-01", "2025-06-30", date(2026, 6, 19)),
            "closed",
        )

    def test_unknown_when_schedule_is_missing(self):
        self.assertEqual(calculate_status("", "", date(2026, 6, 19)), "unknown")


if __name__ == "__main__":
    unittest.main()
