import unittest
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import requests

from app.direct.collectors import (
    DirectAnnouncementSource,
    _announcement,
    _fetch_applyhome,
    _fetch_lh,
    _fetch_lh_wrtanc_boards,
    _json_items,
    _lh_notice_url,
    _gh_detail_district,
    _parse_gh_apply_list,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DirectCollectorTests(unittest.TestCase):
    def test_gh_apply_rental_list_is_normalized(self):
        today = date.today().isoformat()
        html = f"""
        <table><tbody><tr>
          <td>1</td><td>국민임대</td><td>
            <a data-pbancno="800" data-pbanckndcd="01" data-biztynm="국민임대">
              고양시 국민임대주택 예비입주자 모집공고
            </a>
          </td><td>경기도</td><td>PDF</td><td>{today}</td>
          <td>2026-07-10</td><td>접수중</td><td>-</td><td>10</td>
        </tr></tbody></table>
        """
        result = _parse_gh_apply_list(html, "rent", "now", 7)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_id, "gh_apply_rent_800")
        self.assertEqual(result[0].category, "GH 임대주택")
        self.assertEqual(result[0].region, "경기")
        self.assertEqual(result[0].district, "고양시")
        self.assertEqual(result[0].apply_end, "2026-07-10")
        self.assertEqual(result[0].metadata["pbanc_no"], "800")
        self.assertIn("searchTitle=", result[0].announcement_url)

    def test_gh_detail_district_ignores_footer_office_address(self):
        text = (
            "공급정보 소재지 경기도 남양주시 다산동 6013 "
            "찾아오시는길 경기도 수원시 영통구 센트럴타운로 43"
        )
        self.assertEqual(_gh_detail_district(text), "남양주시")

    def test_incremental_sync_accumulates_previous_announcements(self):
        with tempfile.TemporaryDirectory() as directory:
            source = DirectAnnouncementSource(
                "", 5, 60, Path(directory) / "announcements.db", 3600
            )
            first = _announcement(
                source_id="sh_1", title="첫 행복주택 입주자 모집공고", organization="SH",
                category="SH 공공주택", region="서울", fetched_at="first",
            )
            second = _announcement(
                source_id="sh_2", title="둘째 행복주택 입주자 모집공고", organization="SH",
                category="SH 공공주택", region="서울", fetched_at="second",
            )
            with mock.patch(
                "app.direct.collectors._fetch_sh", side_effect=[[first], [second]]
            ), mock.patch("app.direct.collectors._fetch_gh", return_value=[]):
                source.fetch(days_back=90, force_refresh=True)
                accumulated = source.fetch(days_back=7, force_refresh=True)
            self.assertEqual({item.source_id for item in accumulated}, {"sh_1", "sh_2"})
            self.assertEqual(source.sync_status["stored_count"], 2)
            self.assertEqual(source.sync_status["last_item_count"], 1)

    def test_lh_direct_list_response_is_supported(self):
        items = _json_items([{"BBS_SN": "10"}, "ignored"])
        self.assertEqual(items, [{"BBS_SN": "10"}])

    def test_lh_wrapped_list_response_is_supported(self):
        items = _json_items([{"dsList": [{"BBS_SN": "11", "BBS_TL": "공고"}]}])
        self.assertEqual(items, [{"BBS_SN": "11", "BBS_TL": "공고"}])

    def test_collector_warning_does_not_expose_service_key(self):
        source = DirectAnnouncementSource(
            "top-secret-key", 5, 0, include_private_housing=True
        )
        response = FakeResponse({})
        response.status_code = 401
        response.reason = "Unauthorized"
        error = requests.HTTPError(
            "401 for https://example.test?serviceKey=top-secret-key",
            response=response,
        )
        with mock.patch("app.direct.collectors._fetch_applyhome", side_effect=error), mock.patch(
            "app.direct.collectors._fetch_lh", return_value=[]
        ), mock.patch("app.direct.collectors._fetch_sh", return_value=[]), mock.patch(
            "app.direct.collectors._fetch_gh", return_value=[]
        ):
            with self.assertRaises(Exception):
                source.fetch()
        warnings = " ".join(source.errors)
        self.assertIn("HTTP 401", warnings)
        self.assertNotIn("top-secret-key", warnings)
        self.assertNotIn("serviceKey", warnings)

    def test_public_only_mode_collects_applyhome_national_housing(self):
        source = DirectAnnouncementSource("key", 5, 60)
        lh_item = _announcement(
            source_id="lh_1", title="LH 행복주택 입주자 모집공고", organization="LH",
            category="LH 공공주택", region="서울", fetched_at="now",
        )
        applyhome_item = _announcement(
            source_id="apt_2",
            title="안양 공공분양",
            organization="청약홈",
            category="APT",
            region="경기",
            fetched_at="now",
            metadata={"house_secd": "01", "house_secd_name": "국민"},
        )
        with mock.patch(
            "app.direct.collectors._fetch_applyhome", return_value=[applyhome_item]
        ) as applyhome, mock.patch(
            "app.direct.collectors._fetch_lh", return_value=[lh_item]
        ), mock.patch("app.direct.collectors._fetch_sh", return_value=[]), mock.patch(
            "app.direct.collectors._fetch_gh", return_value=[]
        ):
            result = source.fetch(force_refresh=True)
        applyhome.assert_called_once()
        self.assertEqual(
            {item.organization for item in result}, {"LH", "청약홈"}
        )

    def test_public_only_mode_hides_private_but_keeps_public_applyhome(self):
        with tempfile.TemporaryDirectory() as directory:
            source = DirectAnnouncementSource(
                "", 5, 60, Path(directory) / "announcements.db"
            )
            public = _announcement(
                source_id="sh_1", title="SH 공공주택", organization="SH",
                category="SH 공공주택", region="서울", fetched_at="now",
            )
            private = _announcement(
                source_id="apt_1", title="민영 아파트", organization="청약홈",
                category="APT", region="서울", fetched_at="now",
            )
            applyhome_public = _announcement(
                source_id="apt_2",
                title="국민주택 공공분양",
                organization="청약홈",
                category="APT",
                region="경기",
                fetched_at="now",
                metadata={"house_secd": "01", "house_secd_name": "국민"},
            )
            source.repository.upsert(
                [public.to_dict(), private.to_dict(), applyhome_public.to_dict()],
                "2026-06-21T00:00:00+00:00",
            )
            result = source._stored_items()
        self.assertEqual(
            {item.source_id for item in result}, {"sh_1", "apt_2"}
        )

    def test_applyhome_public_mode_keeps_only_apt_national_housing(self):
        payload = {
            "data": [
                {
                    "PBLANC_NO": "public-1",
                    "HOUSE_NM": "안양 공공분양",
                    "HOUSE_SECD": "01",
                    "HOUSE_SECD_NM": "국민",
                    "PBLANC_URL": "https://example.com/public",
                },
                {
                    "PBLANC_NO": "private-1",
                    "HOUSE_NM": "민영 아파트",
                    "HOUSE_SECD": "02",
                    "HOUSE_SECD_NM": "민영",
                    "PBLANC_URL": "https://example.com/private",
                },
            ]
        }
        with mock.patch(
            "app.direct.collectors.requests.get", return_value=FakeResponse(payload)
        ) as request:
            result = _fetch_applyhome("key", 2, 5, "now")
        self.assertEqual([item.source_id for item in result], ["apt_public-1"])
        self.assertEqual(result[0].metadata["house_secd"], "01")
        self.assertEqual(request.call_count, 1)

    def test_five_applyhome_channels_are_normalized(self):
        payload = {
            "data": [{
                "PBLANC_NO": "20260001",
                "HOUSE_NM": "테스트 공급",
                "SUBSCRPT_AREA_CODE_NM": "서울",
                "HSSPLY_ADRES": "서울특별시 강서구 테스트로 1",
                "RCEPT_BGNDE": "20260601",
                "RCEPT_ENDDE": "20260630",
                "TOT_SUPLY_HSHLDCO": 100,
                "PBLANC_URL": "https://example.com",
            }]
        }
        with mock.patch("app.direct.collectors.requests.get", return_value=FakeResponse(payload)):
            result = _fetch_applyhome(
                "key", 2, 5, "now", include_private_housing=True
            )
        self.assertEqual(len(result), 5)
        self.assertEqual(len({item.category for item in result}), 5)
        self.assertTrue(all(item.source_type == "direct_collector" for item in result))

    def test_lh_rental_wrtanc_detail_url_is_built_from_pan_id(self):
        url = _lh_notice_url(
            {
                "BBS_TL": "서울 행복주택 입주자 모집공고",
                "PAN_ID": "PAN123",
                "AIS_TP_CD": "061339",
                "PAN_KD_CD": "01",
            },
            "행복주택",
        )
        self.assertIn("selectWrtancInfo.do", url)
        self.assertIn("mi=1026", url)
        self.assertIn("uppAisTpCd=06", url)
        self.assertIn("panId=PAN123", url)

    def test_lh_sale_wrtanc_detail_url_is_built_from_pan_id(self):
        url = _lh_notice_url(
            {
                "BBS_TL": "인천 공공분양 입주자 모집공고",
                "PAN_ID": "SALE123",
                "AIS_TP_CD": "050000",
            },
            "공공분양",
        )
        self.assertIn("selectWrtancInfo.do", url)
        self.assertIn("mi=1027", url)
        self.assertIn("uppAisTpCd=05", url)
        self.assertIn("panId=SALE123", url)

    def test_lh_existing_link_url_is_preserved(self):
        url = _lh_notice_url({"LINK_URL": "https://apply.lh.or.kr/custom"}, "행복주택")
        self.assertEqual(url, "https://apply.lh.or.kr/custom")

    def test_lh_list_link_url_is_replaced_when_pan_id_exists(self):
        url = _lh_notice_url(
            {
                "LINK_URL": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1027",
                "PAN_ID": "SALE123",
                "BBS_TL": "성남 공공분양 입주자모집공고",
            },
            "공공분양",
        )
        self.assertIn("selectWrtancInfo.do", url)
        self.assertIn("mi=1027", url)
        self.assertIn("panId=SALE123", url)

    def test_lh_pan_id_response_is_kept_and_linked_to_wrtanc_detail(self):
        payload = {
            "data": [
                {
                    "PAN_ID": "PAN123",
                    "BBS_TL": "서울 행복주택 입주자 모집공고",
                    "BBS_WOU_DTTM": date.today().isoformat(),
                    "AIS_TP_CD_NM": "행복주택",
                    "AIS_TP_CD": "061339",
                }
            ]
        }
        with mock.patch("app.direct.collectors.requests.get", return_value=FakeResponse(payload)):
            result = _fetch_lh("key", 2, 5, "now")
        self.assertEqual([item.source_id for item in result], ["lh_PAN123"])
        self.assertIn("selectWrtancInfo.do", result[0].announcement_url)
        self.assertIn("panId=PAN123", result[0].announcement_url)

    def test_lh_wrtanc_board_rows_are_collected_with_detail_url(self):
        html = """
        <table class="bbs_ListA"><tbody><tr>
          <td>1</td><td>공공분양(신혼희망)</td>
          <td class="bbs_tit"><a class="wrtancInfoBtn" data-id1="0000061094" data-id2="02" data-id3="39" data-id4="39">
            <span>e편한세상 분당 퍼스트빌리지 입주자모집공고 <em class="day">1일전</em></span>
          </a></td>
          <td>경기도</td><td></td><td>2026.05.29</td><td>2026.07.21</td><td>공고중</td><td>1</td>
        </tr></tbody></table>
        """
        with mock.patch("app.direct.collectors.requests.get", return_value=FakeResponse({})) as request:
            request.return_value.text = html
            request.return_value.encoding = "utf-8"
            request.return_value.apparent_encoding = "utf-8"
            result = _fetch_lh_wrtanc_boards(90, 5, "now")
        self.assertEqual([item.source_id for item in result], ["lh_0000061094"])
        self.assertEqual(result[0].region, "경기")
        self.assertIn("selectWrtancInfo.do", result[0].announcement_url)
        self.assertIn("panId=0000061094", result[0].announcement_url)

    def test_lh_standard_response_is_normalized(self):
        payload = {
            "response": {
                "body": {
                    "items": {
                        "item": {
                            "BBS_SN": "10",
                            "BBS_TL": "서울 행복주택 입주자 모집공고",
                            "BBS_WOU_DTTM": date.today().isoformat(),
                            "AIS_TP_CD_NM": "행복주택",
                            "LINK_URL": "https://apply.lh.or.kr",
                        }
                    }
                }
            }
        }
        with mock.patch("app.direct.collectors.requests.get", return_value=FakeResponse(payload)) as request:
            result = _fetch_lh("key", 2, 5, "now")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].organization, "LH")
        self.assertEqual(result[0].region, "서울")
        params = request.call_args_list[0].kwargs["params"]
        self.assertEqual(params["ServiceKey"], "key")
        self.assertEqual(params["PG_SZ"], "100")
        self.assertEqual(params["PAGE"], "1")
        self.assertIn("SCH_ST_DT", params)
        self.assertIn("SCH_ED_DT", params)


if __name__ == "__main__":
    unittest.main()
