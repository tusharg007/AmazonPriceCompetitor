"""Bounded, app-owned sliding windows for the local single-process API."""

import math
import time
from collections import deque
from collections.abc import Callable

from app.core.exceptions import RateLimitError


class RequestLimiter:
    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.clock = limit, clock
        self.windows: dict[tuple[str, str], deque[float]] = {}

    def check(self, client: str, scope: str) -> None:
        # No awaits: a check/update is atomic within the API event loop.
        now = self.clock()
        for key in list(self.windows):
            existing = self.windows[key]
            while existing and existing[0] <= now - 60:
                existing.popleft()
            if not existing:
                del self.windows[key]
        key = (client, scope)
        window = self.windows.get(key)
        if window is None:
            # Fail closed instead of evicting active clients and resetting their budget.
            if len(self.windows) >= 4096:
                raise RateLimitError(60)
            window = self.windows[key] = deque()
        if len(window) >= self.limit:
            raise RateLimitError(max(1, math.ceil(60 - (now - window[0]))))
        window.append(now)
