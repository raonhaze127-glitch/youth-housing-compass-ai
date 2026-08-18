import unittest
from unittest import mock

from app.direct import http_compat


class HttpCompatTests(unittest.TestCase):
    def test_curl_text_falls_back_to_cp949(self) -> None:
        with mock.patch.object(
            http_compat,
            "curl_bytes",
            return_value="공고중".encode("cp949"),
        ):
            self.assertEqual(http_compat.curl_text("https://example.com", 5), "공고중")


if __name__ == "__main__":
    unittest.main()
