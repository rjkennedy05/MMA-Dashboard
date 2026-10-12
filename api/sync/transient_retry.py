from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


TRANSIENT_CONNECTION_MARKERS = (
    "connectionterminated",
    "remoteprotocolerror",
    "server disconnected",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "goaway",
    "readerror",
    "read timeout",
    "readtimeout",
    "connect timeout",
    "connecttimeout",
)


def _error_chain_text(error: BaseException) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.extend((str(current), repr(current)))
        current = current.__cause__ or current.__context__
    return " ".join(messages).casefold()


def is_transient_connection_error(error: BaseException) -> bool:
    text = _error_chain_text(error)
    return any(marker in text for marker in TRANSIENT_CONNECTION_MARKERS)


def run_with_transient_retry(
    operation: Callable[[], Any],
    *,
    label: str,
    attempts: int = 4,
    on_retry: Callable[[int, BaseException], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> Any:
    if attempts < 1:
        raise ValueError("Retry attempts must be at least one.")

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as error:
            if (
                attempt >= attempts
                or not is_transient_connection_error(error)
            ):
                raise
            if on_retry:
                on_retry(attempt, error)
            delay = min(4.0, 0.5 * (2 ** (attempt - 1)))
            print(
                f"  TRANSIENT CONNECTION — retrying {label} "
                f"({attempt}/{attempts - 1})"
            )
            sleeper(delay)

    raise RuntimeError(f"Retry loop ended unexpectedly for {label}.")
