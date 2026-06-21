import unittest

from fastapi.testclient import TestClient

from app.main import app


class AnnouncementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "source": "sample",
                "upstream_features": False,
                "direct_features": False,
                "collector_warnings": [],
                "sync": None,
            },
        )

    def test_sample_announcements(self):
        response = self.client.get("/v1/announcements")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "sample")
        self.assertEqual(payload["count"], 6)
        self.assertEqual(len(payload["announcements"]), 6)

    def test_region_filter_keeps_national_programs(self):
        response = self.client.get("/v1/announcements", params={"region": "서울"})
        self.assertEqual(response.status_code, 200)
        regions = {item["region"] for item in response.json()["announcements"]}
        self.assertTrue(regions.issubset({"서울", "전국"}))

    def test_upstream_feature_requires_configuration(self):
        response = self.client.post("/v1/eligibility/score", json={"profile": {}})
        self.assertEqual(response.status_code, 503)

if __name__ == "__main__":
    unittest.main()
