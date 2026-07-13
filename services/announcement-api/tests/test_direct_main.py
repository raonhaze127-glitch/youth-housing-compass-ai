import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main_module
from app.direct.collectors import DirectAnnouncementSource, _announcement
from app.direct.features import DirectFeatureClient


class DirectApiTests(unittest.TestCase):
    def setUp(self):
        self.source = DirectAnnouncementSource("", 5, 900)
        self.source._cache = [
            _announcement(
                source_id="sh_10", title="청년주택 입주자 모집공고", organization="SH",
                category="SH 공공주택", region="서울", start="2026-06-01", end="2026-06-30",
                url="https://example.com", fetched_at="2026-06-20T00:00:00+00:00",
            )
        ]
        self.source._cache_at = time.time()
        self.features = DirectFeatureClient(self.source, 5)
        self.client = TestClient(main_module.app)

    def test_direct_announcements_and_score(self):
        with mock.patch.object(main_module, "source", self.source), mock.patch.object(
            main_module, "feature_client", self.features
        ):
            announcements = self.client.get("/v1/announcements")
            score = self.client.post("/v1/eligibility/score", json={"profile": {"age": 28}})
        self.assertEqual(announcements.status_code, 200)
        self.assertEqual(announcements.json()["source"], "direct")
        self.assertEqual(announcements.json()["announcements"][0]["source_type"], "direct_collector")
        self.assertEqual(score.status_code, 200)
        self.assertEqual(score.json()["scores"]["max_total"], 84)

    def test_manual_incremental_sync_endpoint(self):
        with mock.patch.object(main_module, "source", self.source), mock.patch.object(
            self.source, "fetch", return_value=self.source._cache
        ) as fetch:
            response = self.client.post(
                "/v1/announcements/sync", json={"days_back": 7}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "incremental")
        fetch.assert_called_once_with(days_back=7, force_refresh=True)

    def test_manual_incremental_sync_defaults_to_three_days(self):
        with mock.patch.object(main_module, "source", self.source), mock.patch.object(
            self.source, "fetch", return_value=self.source._cache
        ) as fetch:
            response = self.client.post("/v1/announcements/sync", json={})
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(days_back=3, force_refresh=True)


if __name__ == "__main__":
    unittest.main()
