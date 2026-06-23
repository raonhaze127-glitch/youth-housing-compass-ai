import unittest
from unittest.mock import patch

from app.direct.interpretation import (
    _select_enrichment_candidates,
    enrich_announcement,
    fetch_notice_text,
    interpret_notice_text,
    is_public_recruitment_notice,
    _sh_attachment_urls,
)
from app.models import Announcement


class DirectInterpretationTests(unittest.TestCase):
    @patch("app.direct.interpretation.curl_text")
    def test_fetches_gh_apply_detail_with_post(self, curl):
        curl.return_value = "<html><body>신청자격 무주택세대구성원 접수기간 2026.07.01 ~ 2026.07.03</body></html>"
        announcement = Announcement(
            id="direct:gh_apply_purchase_795",
            source_id="gh_apply_purchase_795",
            source_type="direct_collector",
            title="26년 매입임대주택 입주자 모집공고",
            organization="GH",
            category="GH 매입임대",
            region="경기",
            district="",
            housing_type="매입임대",
            target=(),
            apply_start="",
            apply_end="",
            status="unknown",
            announcement_url="https://apply.gh.or.kr/sb/sr/sr7155/selectPbancRentHouseList.do",
            summary="",
            eligibility_summary="",
            benefit_summary="",
            required_documents=(),
            metadata={
                "detail_url": "https://apply.gh.or.kr/sb/sr/sr7155/selectPbancDetailView.do",
                "pbanc_no": "795",
                "pbanc_kind_code": "01",
                "business_type_name": "매입임대",
            },
        )
        text, attachments = fetch_notice_text(announcement)
        self.assertIn("신청자격", text)
        self.assertEqual(attachments, [])
        self.assertEqual(curl.call_args.kwargs["data"]["pbancNo"], "795")

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

    def test_filters_lh_follow_up_posts_but_keeps_corrected_notice(self):
        excluded_titles = (
            "[접수마감 결과안내] 시흥시 국민임대 예비입주자 모집",
            "본청약 입주자 모집 배정물량 안내",
            "국민임대 입주자 모집 공급대상주택 게시",
            "예비입주자 모집 서류제출 안내",
            "입주자 모집 신청 결과 및 마감단지 게시",
            "입주자 모집 주택사진 정정 안내",
        )
        for title in excluded_titles:
            with self.subTest(title=title):
                self.assertFalse(
                    is_public_recruitment_notice(
                        {
                            "organization": "LH",
                            "title": title,
                            "housing_type": "국민임대",
                        }
                    )
                )

        self.assertTrue(
            is_public_recruitment_notice(
                {
                    "organization": "LH",
                    "title": "[정정공고] 고양시 국민임대주택 예비입주자 모집공고",
                    "housing_type": "국민임대",
                }
            )
        )

    def test_balances_enrichment_across_public_organizations(self):
        announcements = [
            Announcement(
                id=f"direct:{organization.lower()}_{index}",
                source_id=f"{organization.lower()}_{index}",
                source_type="direct_collector",
                title=f"{organization} 공공임대 입주자 모집공고 {index}",
                organization=organization,
                category="공공임대",
                region="전국",
                district="",
                housing_type="공공임대",
                target=(),
                apply_start="",
                apply_end="",
                status="unknown",
                announcement_url="https://example.com/notice",
                summary="",
                eligibility_summary="",
                benefit_summary="",
                required_documents=(),
            )
            for organization in ("LH", "SH", "GH")
            for index in range(4)
        ]

        selected = _select_enrichment_candidates(announcements, limit=6)
        self.assertEqual(
            [item.organization for item in selected],
            ["LH", "SH", "GH", "LH", "SH", "GH"],
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

    def test_extracts_gh_online_application_period(self):
        result = interpret_notice_text(
            "접수기간 정정 2026.06.11 ~ 2026.06.11\n"
            "공급일정\n온라인접수기간\n:\n2026.06.30 10:00 ~ 2026.07.02 18:00"
        )
        self.assertEqual(result["apply_start"], "2026-06-30")
        self.assertEqual(result["apply_end"], "2026-07-02")

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
