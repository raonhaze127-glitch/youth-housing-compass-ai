import unittest
from datetime import date
from unittest import mock

from app.direct.collectors import _fetch_applyhome, _fetch_lh


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DirectCollectorTests(unittest.TestCase):
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
        with mock.patch("app.direct.collectors.requests.get", return_value=FakeResponse(payload)):
            result = _fetch_lh("key", 2, 5, "now")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].organization, "LH")
        self.assertEqual(result[0].region, "서울")


if __name__ == "__main__":
    unittest.main()
