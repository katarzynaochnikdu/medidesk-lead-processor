"""
Rate limiter for API calls.
"""

import asyncio
import time
from typing import Optional


class RateLimiter:
    """
    Async rate limiter (token bucket algorithm).

    Użycie:
        limiter = RateLimiter(rate=1.0)  # 1 request/second
        async with limiter:
            # Make API call
            pass
    """

    def __init__(self, rate: float):
        """
        Initialize rate limiter.

        Args:
            rate: Max requests per second
        """
        self.rate = rate
        self.min_interval = 1.0 / rate
        self.last_call: Optional[float] = None
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        """Acquire rate limit."""
        async with self._lock:
            if self.last_call is not None:
                # Calculate time since last call
                elapsed = time.time() - self.last_call
                wait_time = self.min_interval - elapsed

                if wait_time > 0:
                    # Wait to respect rate limit
                    await asyncio.sleep(wait_time)

            # Update last call time
            self.last_call = time.time()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Release rate limit."""
        pass

    async def wait_if_needed(self):
        """
        Wait if needed to respect rate limit.
        Alternative to context manager.
        """
        async with self:
            pass
