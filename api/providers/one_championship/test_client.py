import unittest

import requests

from client import (
    OneChampionshipClient,
    OneChampionshipError,
)


class FakeResponse:
    def __init__(
        self,
        text="<html>onefc.com</html>",
        error=None,
        payload=None,
    ):
        self.text = text
        self.error = error
        self.payload = payload

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class OneChampionshipClientTests(unittest.TestCase):
    def test_listing_uses_official_events_url(self):
        session = FakeSession(FakeResponse())
        client = OneChampionshipClient(session=session, timeout=12)

        result = client.get_event_listing()

        self.assertIn("onefc.com", result)
        self.assertEqual(client.request_count, 1)
        self.assertEqual(session.calls[0][0], "https://www.onefc.com/events/")
        self.assertEqual(session.calls[0][1]["timeout"], 12)

    def test_rejects_non_one_event_urls(self):
        client = OneChampionshipClient(session=FakeSession(FakeResponse()))

        with self.assertRaises(OneChampionshipError):
            client.get_event_page("https://example.com/events/fake/")

    def test_wraps_request_errors(self):
        response = FakeResponse(
            error=requests.HTTPError("503 Server Error")
        )
        client = OneChampionshipClient(session=FakeSession(response))

        with self.assertRaisesRegex(
            OneChampionshipError, "ONE Championship request failed"
        ):
            client.get_event_listing()

    def test_reads_official_event_status(self):
        session = FakeSession(
            FakeResponse(payload={"is_past": True, "is_finished": True})
        )
        client = OneChampionshipClient(session=session)

        payload = client.get_event_status(
            "https://www.onefc.com/wp-json/public/v2/events/546347"
        )

        self.assertTrue(payload["is_finished"])
        self.assertEqual(client.request_count, 1)


if __name__ == "__main__":
    unittest.main()
