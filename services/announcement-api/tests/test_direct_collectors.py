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
    _json_items,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DirectCollectorTests(unittest.TestCase):
    def test_incremental_sync_accumulates_previous_announcements(self):
        with tempfile.TemporaryDirectory() as directory:
            source = DirectAnnouncementSource(
                "", 5, 60, Path(directory) / "announcements.db", 3600
            )
            first = _announcement(
                source_id="sh_1", title="첫 공고", organization="SH",
                category="SH 공공주택", region="서울", fetched_at="first",
            )
            second = _announcement(
                source_id="sh_2", title="둘째 공고", organization="SH",
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

    def test_public_only_mode_skips_applyhome_collection(self):
        source = DirectAnnouncementSource("key", 5, 60)
        lh_item = _announcement(
            source_id="lh_1", title="LH 공공주택", organization="LH",
            category="LH 공공주택", region="서울", fetched_at="now",
        )
        with mock.patch("app.direct.collectors._fetch_applyhome") as applyhome, mock.patch(
            "app.direct.collectors._fetch_lh", return_value=[lh_item]
        ), mock.patch("app.direct.collectors._fetch_sh", return_value=[]), mock.patch(
            "app.direct.collectors._fetch_gh", return_value=[]
        ):
            result = source.fetch(force_refresh=True)
        applyhome.assert_not_called()
        self.assertEqual([item.organization for item in result], ["LH"])

    def test_public_only_mode_hides_stored_applyhome_announcements(self):
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
            source.repository.upsert(
                [public.to_dict(), private.to_dict()], "2026-06-21T00:00:00+00:00"
            )
            result = source._stored_items()
        self.assertEqual([item.source_id for item in result], ["sh_1"])

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
            result = _fetch_applyhome("key", 2, 5, "now")
        self.assertEqual(len(result), 5)
        self.assertEqual(len({item.category for item in result}), 5)
        self.assertTrue(all(item.source_type == "direct_collector" for item in result))

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
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["ServiceKey"], "key")
        self.assertEqual(params["PG_SZ"], "100")
        self.assertEqual(params["PAGE"], "1")
        self.assertIn("SCH_ST_DT", params)
        self.assertIn("SCH_ED_DT", params)


if __name__ == "__main__":
    unittest.main()
