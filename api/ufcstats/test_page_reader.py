from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from page_reader import UfcstatsPageReader


class FakePage:
    def goto(self, *_args, **_kwargs) -> None:
        return None

    def wait_for_load_state(self, *_args, **_kwargs) -> None:
        return None

    def wait_for_timeout(self, *_args, **_kwargs) -> None:
        return None

    def content(self) -> str:
        return "<html>fight</html>"

    def close(self) -> None:
        return None


class FakeBrowser:
    def new_page(self) -> FakePage:
        return FakePage()

    def close(self) -> None:
        return None


class FakeChromium:
    def __init__(self, thread_ids: list[int]) -> None:
        self.thread_ids = thread_ids

    def launch(self, **_kwargs) -> FakeBrowser:
        self.thread_ids.append(threading.get_ident())
        return FakeBrowser()


class FakePlaywright:
    def __init__(self, thread_ids: list[int]) -> None:
        self.chromium = FakeChromium(thread_ids)

    def start(self) -> "FakePlaywright":
        return self

    def stop(self) -> None:
        return None


class UfcstatsPageReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_playwright_runs_off_the_asyncio_thread(self) -> None:
        main_thread_id = threading.get_ident()
        worker_thread_ids: list[int] = []

        def fake_sync_playwright() -> FakePlaywright:
            return FakePlaywright(worker_thread_ids)

        with patch("page_reader.sync_playwright", fake_sync_playwright):
            await asyncio.sleep(0)
            with UfcstatsPageReader() as reader:
                html = reader.read("https://example.test/fight", wait_ms=0)

        self.assertEqual(html, "<html>fight</html>")
        self.assertEqual(len(worker_thread_ids), 1)
        self.assertNotEqual(worker_thread_ids[0], main_thread_id)


if __name__ == "__main__":
    unittest.main()
