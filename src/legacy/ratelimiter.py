import asyncio
import logging
import random
import time

from src.core.objects import ABCScan, Manga
from src.core.scanners import SCANLATORS


class RateLimiter:
    SCANLATORS: dict[str, ABCScan] = SCANLATORS
    _logger = logging.getLogger("RateLimiter")

    def __init__(self):
        self._last_request_times = {}

    @staticmethod
    def get_scanlator_key(manga: Manga):
        """
        Returns the scanlator key for a given Manga object, which corresponds to one of the keys in self.SCANLATORS.
        """
        return manga.scanlator

    async def delay_if_necessary(self, manga: Manga):
        """
        Delays the current coroutine if the previous request to the same scanlator was made not too long ago.
        """

        scanlators_to_ignore_rate_limits_for = ["mangadex"]

        scanlator_key = manga.scanlator
        if scanlator_key in scanlators_to_ignore_rate_limits_for:
            return

        last_request_time = self._last_request_times.get(scanlator_key, None)

        if last_request_time is not None:
            time_since_last_request = time.monotonic() - last_request_time
            min_time_between_requests = self.SCANLATORS[
                scanlator_key
            ].MIN_TIME_BETWEEN_REQUESTS
            if time_since_last_request < min_time_between_requests:
                time_to_sleep = (
                        min_time_between_requests
                        - time_since_last_request
                        + random.uniform(0.5, 1.5)
                )
                self._logger.debug(
                    f"Delaying request to {scanlator_key} for {time_to_sleep} seconds."
                )
                await asyncio.sleep(time_to_sleep)

        self._last_request_times[scanlator_key] = time.monotonic()
