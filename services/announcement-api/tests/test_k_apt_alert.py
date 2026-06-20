import unittest

from app.sources.k_apt_alert import normalize_announcement


class KAptAlertNormalizerTests(unittest.TestCase):
    def test_normalizes_applyhome_announcement(self):
        result = normalize_announcement(
            {
                "id": "apt_123",
                "name": "테스트 청약",
                "region": "서울",
                "district": "강서구",
                "period": "20260620 ~ 20260625",
                "rcept_end": "20260625",
                "house_type": "민영",
                "house_category": "APT",
                "total_units": "1,234",
                "url": "https://example.com/notice",
            },
            "2026-06-19T00:00:00Z",
        )

        self.assertEqual(result.id, "kapt:apt_123")
        self.assertEqual(result.organization, "청약홈")
        self.assertEqual(result.apply_start, "2026-06-20")
        self.assertEqual(result.apply_end, "2026-06-25")
        self.assertEqual(result.total_units, 1234)
        self.assertTrue(result.schedule_confirmed)

    def test_missing_schedule_is_not_guessed(self):
        result = normalize_announcement(
            {
                "id": "gh_123",
                "name": "GH 테스트 공고",
                "region": "경기",
                "house_category": "GH 공공주택",
                "schedule_source": "unavailable",
            },
            "2026-06-19T00:00:00Z",
        )

        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.schedule_confirmed)


if __name__ == "__main__":
    unittest.main()
