import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.direct.collectors import DirectAnnouncementSource, _announcement
from app.direct.features import DirectFeatureClient, _section_windows


def sample_announcement(source_id="sh_1", title="청년주택 입주자 모집공고"):
    return _announcement(
        source_id=source_id,
        title=title,
        organization="SH",
        category="SH 공공주택",
        region="서울",
        start="2026-06-01",
        end="2026-06-30",
        url="https://example.com/notice",
        fetched_at="2026-06-20T00:00:00+00:00",
    )


class DirectFeatureTests(unittest.TestCase):
    def setUp(self):
        self.source = DirectAnnouncementSource("", 5, 900)
        self.source._cache = [sample_announcement()]
        self.source._cache_at = time.time()
        self.client = DirectFeatureClient(self.source, 5)

    def test_calendar_is_generated_locally(self):
        result = self.client.calendar("sh_1")
        text = result.content.decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("20260601", text)

    def test_sections_are_found_without_llm(self):
        sections = _section_windows("신청자격 무주택 청년 공급일정 6월 30일 제출서류 주민등록등본")
        self.assertIn("자격", sections)
        self.assertIn("공급일정", sections)
        self.assertIn("준비서류", sections)

    def test_competition_falls_back_to_labeled_estimate(self):
        result = self.client.competition("sh_1")
        self.assertEqual(result["source"], "statistical_estimate")

    def test_direct_source_keeps_partial_success(self):
        source = DirectAnnouncementSource("", 5, 60)
        item = sample_announcement()
        with mock.patch("app.direct.collectors._fetch_sh", return_value=[item]), mock.patch(
            "app.direct.collectors._fetch_gh", side_effect=RuntimeError("site changed")
        ):
            result = source.fetch()
        self.assertEqual([entry.source_id for entry in result], ["sh_1"])
        self.assertTrue(any("gh 수집 실패" in warning for warning in source.errors))

    def test_change_history_hides_private_announcements(self):
        with tempfile.TemporaryDirectory() as directory:
            source = DirectAnnouncementSource(
                "", 5, 60, Path(directory) / "announcements.db"
            )
            public = sample_announcement()
            private = _announcement(
                source_id="apt_1", title="민영 아파트", organization="청약홈",
                category="APT", region="서울", fetched_at="now",
            )
            source.repository.upsert(
                [public.to_dict(), private.to_dict()], "2026-06-21T00:00:00+00:00"
            )
            client = DirectFeatureClient(source, 5)
            with mock.patch.object(source, "fetch", return_value=[public]):
                result = client.changes()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["changes"][0]["organization"], "SH")


if __name__ == "__main__":
    unittest.main()
