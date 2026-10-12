import unittest

from client import BkfcClient, BkfcProviderError


class FakeResponse:
    def __init__(self, text="<html>BKFC</html>", payload=None, status_code=200):
        self.text = text
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class BkfcClientTests(unittest.TestCase):
    def test_reads_html_and_counts_requests(self):
        session = FakeSession(FakeResponse())
        client = BkfcClient(session=session)

        html = client.get_upcoming()

        self.assertIn("BKFC", html)
        self.assertEqual(client.request_count, 1)
        self.assertIn("User-Agent", session.calls[0][1]["headers"])

    def test_reads_official_stats_json(self):
        payload = {"Bouts": {"Bout1": {"BoutID": 10}}}
        client = BkfcClient(
            session=FakeSession(FakeResponse(payload=payload))
        )
        self.assertEqual(
            client.get_event_stats("https://xapi.mmareg.com/event")["Bouts"],
            payload["Bouts"],
        )

    def test_rejects_stats_without_bouts(self):
        client = BkfcClient(
            session=FakeSession(FakeResponse(payload={"EventID": 1}))
        )
        with self.assertRaises(BkfcProviderError):
            client.get_event_stats("https://xapi.mmareg.com/event")


if __name__ == "__main__":
    unittest.main()
