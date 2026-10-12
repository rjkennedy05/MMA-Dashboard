import unittest

from client import LfaClient, LfaProviderError


class FakeResponse:
    def __init__(self, text="<html>LFA</html>", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class LfaClientTests(unittest.TestCase):
    def test_reads_html_and_counts_requests(self):
        session = FakeSession(FakeResponse())
        client = LfaClient(session=session)

        html = client.get_official_upcoming()

        self.assertIn("LFA", html)
        self.assertEqual(client.request_count, 1)
        self.assertIn("User-Agent", session.calls[0][1]["headers"])

    def test_rejects_non_html_response(self):
        client = LfaClient(session=FakeSession(FakeResponse("{}")))
        with self.assertRaises(LfaProviderError):
            client.get_sherdog_index()


if __name__ == "__main__":
    unittest.main()
