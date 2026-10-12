from __future__ import annotations

from queue import Queue
from threading import Thread
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


class UfcstatsPageReader:
    """Reuse one Chromium page on a worker thread for a UFCStats batch.

    Playwright's synchronous API cannot start on a thread that already owns an
    asyncio event loop. The dashboard's provider stack can create such a loop,
    so Chromium lives on one dedicated worker thread for the whole batch.
    """

    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self._commands: Queue[tuple[str, Any]] = Queue()
        self._responses: Queue[tuple[str, Any]] = Queue()
        self._worker: Thread | None = None

    def __enter__(self) -> "UfcstatsPageReader":
        if self._worker is not None:
            raise RuntimeError("UFCStats page reader is already open.")

        self._worker = Thread(
            target=self._run_worker,
            name="ufcstats-playwright",
            daemon=True,
        )
        self._worker.start()
        status, payload = self._responses.get()
        if status != "ready":
            self._worker.join()
            self._worker = None
            raise RuntimeError(
                f"UFCStats browser could not start: {payload}"
            ) from payload
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        worker = self._worker
        if worker is None:
            return

        if worker.is_alive():
            self._commands.put(("close", None))
            self._responses.get()
        worker.join()
        self._worker = None

    def read(self, url: str, *, wait_ms: int = 3000, attempts: int = 3) -> str:
        if self._worker is None or not self._worker.is_alive():
            raise RuntimeError("UFCStats page reader is not open.")

        self._commands.put(
            (
                "read",
                {
                    "url": url,
                    "wait_ms": wait_ms,
                    "attempts": attempts,
                },
            )
        )
        status, payload = self._responses.get()
        if status == "ok":
            return str(payload)
        raise RuntimeError(str(payload)) from payload

    @staticmethod
    def _read_page(page, url: str, wait_ms: int, attempts: int) -> str:
        """Read one fight page using the worker-owned Playwright page."""
        last_error: Exception | None = None
        for _attempt in range(max(1, attempts)):
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                page.wait_for_timeout(wait_ms)
                return page.content()
            except PlaywrightError as error:
                last_error = error
                page.wait_for_timeout(750)

        raise RuntimeError(
            f"UFCStats page did not stabilize after {max(1, attempts)} attempts: "
            f"{last_error}"
        )

    def _run_worker(self) -> None:
        """Own Playwright and service sequential page reads on one thread."""
        playwright = None
        browser = None
        page = None
        ready = False

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page()
            ready = True
            self._responses.put(("ready", None))

            while True:
                command, payload = self._commands.get()
                if command == "close":
                    self._responses.put(("closed", None))
                    return
                if command != "read":
                    self._responses.put(
                        ("error", RuntimeError(f"Unknown command: {command}"))
                    )
                    continue

                try:
                    html = self._read_page(page=page, **payload)
                    self._responses.put(("ok", html))
                except Exception as error:
                    self._responses.put(("error", error))
        except Exception as error:
            if not ready:
                self._responses.put(("error", error))
        finally:
            if page is not None:
                page.close()
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()
