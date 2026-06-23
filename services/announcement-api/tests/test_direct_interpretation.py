import unittest
from unittest.mock import patch

from app.direct.interpretation import (
    enrich_announcement,
    interpret_notice_text,
    is_public_recruitment_notice,
    _sh_attachment_urls,
)
from app.models import Announcement


class DirectInterpretationTests(unittest.TestCase):
    def test_filters_results_and_non_housing_posts(self):
        self.assertTrue(
            is_public_recruitment_notice(
                {
                    "organization": "GH",
                    "title": "다산 통합공공임대주택 입주자 모집 공고",
                    "housing_type": "통합공공임대",
                }
            )
        )
        self.assertFalse(
            is_public_recruitment_notice(
                {
                    "organization": "LH",
                    "title": "국민임대주택 예비입주자 모집 접수 결과 게시",
                    "housing_type": "국민임대",
                }
            )
        )
        self.assertFalse(
            is_public_recruitment_notice(
                {
                    "organization": "LH",
                    "title": "업무시설용지 공급공고",
                    "housing_type": "기타용지",
                }
            )
        )

    def test_extracts_grounded_eligibility_fields(self):
        result = interpret_notice_text(
            """
            신청자격 입주자모집공고일 현재 무주택세대구성원인 만 19세 이상 만 39세 이하 청년
            소득기준 도시근로자 월평균 소득의 100% 이하이며 총자산 25,400만원 이하
            접수기간 2026.06.25 ~ 2026.06.30
            임대조건 임대보증금 4,000만원, 월 임대료 18만원
            제출서류 주민등록등본, 가족관계증명서, 금융정보 제공동의서
            """
        )
        self.assertEqual(result["apply_start"], "2026-06-25")
        self.assertEqual(result["apply_end"], "2026-06-30")
        self.assertEqual((result["age_min"], result["age_max"]), (19, 39))
        self.assertTrue(result["homeless_required"])
        self.assertIn("청년", result["target"])
        self.assertIn("주민등록등본", result["required_documents"])
        self.assertIn("100%", result["income_condition"])
        self.assertIn("eligibility", result["sections"])

    def test_extracts_dates_with_weekday_suffixes(self):
        result = interpret_notice_text(
            "접수기간 : 2026.6.30.(화). ~ 2026.7.03.(금). 인터넷 접수"
        )
        self.assertEqual(result["apply_start"], "2026-06-30")
        self.assertEqual(result["apply_end"], "2026-07-03")

    def test_extracts_two_digit_year_from_schedule_table(self):
        result = interpret_notice_text(
            "모집일정 서류접수 26.06.18 ~ 26.06.19 자격심사 개별안내"
        )
        self.assertEqual(result["apply_start"], "2026-06-18")
        self.assertEqual(result["apply_end"], "2026-06-19")

    def test_builds_sh_inno_download_url(self):
        html = """
        <script>
        initParam.downList = [{"brdId":"m_247","seq":"305759","fileTp":"A",
          "fileSeq":"2","oriFileNm":"입주자모집공고.pdf"}];
        </script>
        """
        urls = _sh_attachment_urls(html)
        self.assertEqual(len(urls), 1)
        self.assertIn("innoFD.do", urls[0])
        self.assertIn("seq=305759", urls[0])

    @patch("app.direct.interpretation.fetch_notice_text")
    def test_enrichment_updates_persisted_announcement(self, fetch_notice_text):
        fetch_notice_text.return_value = (
            "신청자격 무주택세대구성원 청년 접수기간 2026-07-01 ~ 2026-07-03 "
            "제출서류 주민등록등본 임대조건 월 임대료 20만원",
            [{"url": "https://apply.lh.or.kr/file.pdf", "type": "pdf", "extracted": True}],
        )
        announcement = Announcement(
            id="direct:lh_1",
            source_id="lh_1",
            source_type="direct_collector",
            title="행복주택 입주자 모집공고",
            organization="LH",
            category="LH 공공주택",
            region="경기",
            district="",
            housing_type="행복주택",
            target=(),
            apply_start="",
            apply_end="",
            status="unknown",
            announcement_url="https://apply.lh.or.kr/view.do?id=1",
            summary="",
            eligibility_summary="",
            benefit_summary="",
            required_documents=(),
        )
        enriched = enrich_announcement(announcement)
        self.assertEqual(enriched.apply_start, "2026-07-01")
        self.assertEqual(enriched.apply_end, "2026-07-03")
        self.assertEqual(enriched.status, "planned")
        self.assertIn("청년", enriched.target)
        self.assertIn("주민등록등본", enriched.required_documents)
        self.assertEqual(enriched.metadata["analysis_source"], "official_notice_and_attachments")


if __name__ == "__main__":
    unittest.main()
