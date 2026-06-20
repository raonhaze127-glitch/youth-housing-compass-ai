import unittest

from app.direct.scoring import competition_estimate, match_payload, score_payload


class DirectScoringTests(unittest.TestCase):
    def test_score_is_deterministic_and_capped(self):
        payload = {
            "profile": {
                "age": 28,
                "no_house": True,
                "no_house_years": 20,
                "dependents": 8,
                "subscription_account": {"years": 20, "deposit_count": 24},
            }
        }
        result = score_payload(payload)
        self.assertEqual(result["scores"]["total"], 84)
        self.assertTrue(result["specials"]["청년"]["eligible"])

    def test_match_levels(self):
        result = match_payload({
            "profile": {"preferred_regions": ["서울"], "preferred_categories": ["APT"]},
            "announcements": [{"id": "a", "region": "서울", "house_category": "APT", "total_units": 100}],
        })
        self.assertEqual(result["matches"][0]["fit_level"], "high")

    def test_competition_is_labeled_as_estimate(self):
        result = competition_estimate({"region": "서울", "size": "소형"})
        self.assertEqual(result["source"], "statistical_estimate")


if __name__ == "__main__":
    unittest.main()
