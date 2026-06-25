import unittest

from scripts.export_snapshot import _deduplicate_snapshot, _validate


class ExportSnapshotTests(unittest.TestCase):
    def test_snapshot_accepts_public_applyhome_and_rejects_private(self):
        public = {
            "id": "direct:apt_1",
            "source_id": "apt_1",
            "title": "안양 공공분양",
            "organization": "청약홈",
            "announcement_url": "https://example.com/public",
            "metadata": {"house_secd": "03", "house_secd_name": "국민"},
        }
        private = {
            **public,
            "id": "direct:apt_2",
            "source_id": "apt_2",
            "metadata": {"house_secd": "01", "house_secd_name": "민영"},
        }

        _validate([public], 1)
        with self.assertRaises(ValueError):
            _validate([private], 1)

    def test_prefers_gh_apply_identity_and_preserves_legacy_analysis(self):
        legacy = {
            "id": "direct:gh_123",
            "source_id": "gh_123",
            "title": "GH youth rental notice",
            "organization": "GH",
            "summary": "analyzed summary",
            "metadata": {
                "notice_date": "2026-06-01",
                "analysis_source": "official_notice_and_attachments",
                "analysis_quality": "medium",
                "source_char_count": 1200,
                "sections": {"eligibility": "legacy analysis"},
                "attachments": [{"url": "https://legacy.example/file.pdf"}],
                "legacy_article_no": "123",
            },
        }
        apply = {
            "id": "direct:gh_apply_rental_456",
            "source_id": "gh_apply_rental_456",
            "title": "GH youth rental notice",
            "organization": "GH",
            "summary": "collector summary",
            "metadata": {
                "notice_date": "2026-06-02",
                "pbanc_no": "456",
                "detail_url": "https://apply.example/detail",
            },
        }

        result = _deduplicate_snapshot([legacy, apply])

        self.assertEqual(len(result), 1)
        preferred = result[0]
        self.assertEqual(preferred["source_id"], "gh_apply_rental_456")
        self.assertEqual(preferred["summary"], "analyzed summary")
        self.assertEqual(preferred["metadata"]["notice_date"], "2026-06-02")
        self.assertEqual(preferred["metadata"]["pbanc_no"], "456")
        self.assertEqual(
            preferred["metadata"]["analysis_source"],
            "official_notice_and_attachments",
        )
        self.assertNotIn("legacy_article_no", preferred["metadata"])

    def test_keeps_newer_gh_apply_analysis_when_both_items_are_analyzed(self):
        legacy = {
            "source_id": "gh_123",
            "title": "GH youth rental notice",
            "organization": "GH",
            "summary": "legacy summary",
            "metadata": {
                "analysis_source": "legacy_analysis",
                "sections": {"eligibility": "legacy"},
            },
        }
        apply = {
            "source_id": "gh_apply_rental_456",
            "title": "GH youth rental notice",
            "organization": "GH",
            "summary": "apply summary",
            "metadata": {
                "analysis_source": "apply_analysis",
                "sections": {"eligibility": "apply"},
                "pbanc_no": "456",
            },
        }

        preferred = _deduplicate_snapshot([legacy, apply])[0]

        self.assertEqual(preferred["summary"], "apply summary")
        self.assertEqual(preferred["metadata"]["analysis_source"], "apply_analysis")
        self.assertEqual(preferred["metadata"]["sections"]["eligibility"], "apply")


if __name__ == "__main__":
    unittest.main()
