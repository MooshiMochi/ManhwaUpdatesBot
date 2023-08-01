import asyncio
import inspect
import logging
import random
import sys
import time
from math import floor
from typing import Any

from src.enums import Hours, Minutes
from .errors import RateLimitExceeded

logger = logging.getLogger("limiter")


class Limiter:
    root: 'Limiter'
    manager: 'Manager'

    def __init__(
            self,
            name: str,
            *,
            calls: int = 15,
            period: int | Minutes | Hours = Minutes.FIVE,
    ):
        self.name = name
        self.disabled: bool = False

        self.period = period if isinstance(period, (int, float)) else period.value

        # split the ratelimit into 75% for user calls and 25% for updates check calls
        self.clamped_user_calls = max(1, min(sys.maxsize, floor(calls * 0.75)))
        self.clamped_auto_calls = max(1, min(sys.maxsize, floor(calls))) - self.clamped_user_calls

        self.user_delay = self.period / self.clamped_user_calls
        self.auto_delay = self.period / self.clamped_auto_calls
        self.clock = time.monotonic if hasattr(time, 'monotonic') else time.time

        self.user_queue = asyncio.Queue(30)
        self.auto_queue = asyncio.Queue(30)

        self._last_request_ts = 0
        self.last_reset = self.clock()
        self.num_auto_calls = 0
        self.num_user_calls = 0

        self.num_user_calls_on_hold: int = 0

    def disable(self) -> None:
        self.disabled = True

    def enable(self) -> None:
        self.disabled = False

    def __period_remaining(self):
        """
        Get the number of seconds remaining in the current period.
        """
        return self.period - (self.clock() - self.last_reset)

    def can_call(self, is_user_call: bool = True, raise_error: bool = False) -> bool:
        """
        Check if the function can be called.
        """
        if self.disabled:
            return True

        if raise_error:
            if not self.can_call(is_user_call):
                raise RateLimitExceeded(self, "429: Too many requests", self.__period_remaining())

        if is_user_call:
            return self.__period_remaining() <= 0 or self.num_user_calls < self.clamped_user_calls
        return self.__period_remaining() <= 0 or self.num_auto_calls < self.clamped_auto_calls

    @property
    def is_delayed(self, is_user_call: bool = True) -> bool:
        """
        Check if the function is delayed.
        """
        if is_user_call:
            return self.clock() - self._last_request_ts < self.user_delay
        return self.clock() - self._last_request_ts < self.auto_delay

    @property
    def delay_remaining(self, is_user_call: bool = True) -> int | float:
        """
        Get the number of seconds remaining in the current delay.
        Returns: (int | float) - The number of seconds remaining in the current delay.
        """
        if is_user_call:
            return max(self.user_delay - (self.clock() - self._last_request_ts), 0)
        return max(self.auto_delay - (self.clock() - self._last_request_ts), 0)

    async def try_acquire(self, max_delay: int = 300, is_user_request: bool = True) -> None:
        """
        Apply internal ratelimiting to the request_coro.
        """

        if self.disabled:
            self._last_request_ts = self.clock()
            return

        period_remaining = self.__period_remaining()

        # If the time window has elapsed then reset.
        if period_remaining <= 0:
            self.num_user_calls = 0
            self.num_auto_calls = 0
            self.last_reset = self.clock()

        if is_user_request:
            self.num_user_calls += 1
            call_count = self.num_user_calls
            clamped_calls_count = self.clamped_user_calls
            self.num_user_calls_on_hold += 1
        else:
            self.num_auto_calls += 1
            call_count = self.num_auto_calls
            clamped_calls_count = self.clamped_auto_calls

        if call_count > clamped_calls_count:
            logger.debug(f"[{self.name}] Limit reached. Delaying for {period_remaining:.2f} seconds")
            if not is_user_request:  # indicates that the request is from the update check task
                await asyncio.sleep(period_remaining)  # wait for the next available call
            else:
                self.num_user_calls_on_hold = max(0, self.num_user_calls_on_hold - 1)
                raise RateLimitExceeded(self, "429: Too many requests", period_remaining)

        elif self.is_delayed:
            if self.delay_remaining > max_delay and is_user_request:
                raise RateLimitExceeded(self, "Delay between request has been reached", self.delay_remaining)
            else:
                extra_delay = random.uniform(0.5, 1.5)  # add a bit of randomness to the delay
                logger.debug(f"[{self.name}] Delaying for {self.delay_remaining + extra_delay:.2f} seconds")
                await asyncio.sleep(self.delay_remaining + extra_delay)  # wait a bit for the delay to end

        if is_user_request:
            self.num_user_calls_on_hold = max(0, self.num_user_calls_on_hold - 1)
        self._last_request_ts = self.clock()

    def __repr__(self):
        return f"<Limiter {self.name} ({self.num_user_calls + self.num_auto_calls}/{self.clamped_auto_calls})>"

    async def __call__(self) -> Any:
        return await self.try_acquire()


class RootLimiter(Limiter):
    def __int__(self):
        super().__init__("root")


_limiterClass = Limiter


class Manager:
    def __init__(self, rootnode: RootLimiter):
        self.root = rootnode
        self.limiterDict = {}
        self.limiterClass = None

    def getLimiter(
            self, name,
            *,
            calls: int = 15,
            period: int | Minutes | Hours = Minutes.FIVE,
            create_if_not_exists: bool = True
    ) -> Limiter | None:
        """
        Get a limiter with the specified name (channel name), creating it
        if it doesn't yet exist and the create_if_not_exists=True.
        """
        if not isinstance(name, str):
            raise TypeError('A limiter name must be a string')
        if name in self.limiterDict:
            rv = self.limiterDict[name]
        else:
            if not create_if_not_exists:
                return
            rv = (self.limiterClass or _limiterClass)(name, calls=calls, period=period)
            rv.manager = self
            self.limiterDict[name] = rv
        return rv

    def setLimiterClass(self, klass):
        """
        Set the class to be used when instantiating a limiter with this Manager.
        """
        if klass != Limiter:
            if not issubclass(klass, Limiter):
                raise TypeError("limiter not derived from rate_limiter.Limiter: "
                                + klass.__name__)
        self.limiterClass = klass


root = RootLimiter("root")
disabled = Limiter("disabled")
disabled.disable()

Limiter.root = root
Limiter.manager = Manager(Limiter.root)


def getLimiter(name=None, *, create_if_not_exists: bool = True) -> Limiter:
    """
    Return a limiter with the specified name, creating it if necessary.

    If no name is specified, return the root limiter.
    """
    if not name or isinstance(name, str) and name == root.name:
        return root
    return Limiter.manager.getLimiter(name, create_if_not_exists=create_if_not_exists)


async def _ping_for_200(request_func, *args, incremental_backoff: bool, **kwargs) -> float | int:
    """
    !!Not for public use!!

    Ping the given URL and return the current timestamp if the response status code is 200.
    """
    if not callable(request_func):
        raise TypeError("The given request function must be callable")
    delay: int | float = 30
    increment_val: int = 60

    while True:
        if inspect.iscoroutinefunction(request_func):
            rv = await request_func(*args, **kwargs)
        else:
            rv = request_func(*args, **kwargs)
        if hasattr(rv, 'status_code') or hasattr(rv, 'status'):
            status_code = rv.status_code if hasattr(rv, 'status_code') else rv.status
            if status_code == 200:
                return time.monotonic() if hasattr(time, 'monotonic') else time.time()
            elif status_code == 403:
                raise ValueError("The given website has temporarily blocked access to this webpage")
        else:
            raise ValueError("The given request function must return a response object with a status code")
        await asyncio.sleep(delay)  # Wait for a short time before checking again
        if incremental_backoff:
            delay += increment_val


async def determineLimitsAndPeriod(
        request_func, *args, incremental_backoff: bool = True, **kwargs
) -> tuple[float | int, float | int]:
    """
    Determine the limit and period for a server/website.
    It is HIGHLY recommended that you use a proxy when using this function.
    This is because the function relies on getting rate limited by the server to determine its limits.

    Note: This function will be unable to determine the period for websites that have a rate limit period < 30 seconds.

    Parameters:
        request_func (function): The function to use to make requests to the server/website. Eg. requests.get
        *args: The arguments to pass to the request function
        incremental_backoff (bool): Whether to use an incremental backoff when determining the period.
            This is recommended as it will reduce the chance of getting temp-banned by the server.
            You should only set this to False if you are CONFIDENT that the server has a short rate limit reset period.
        **kwargs: The keyword arguments to pass to the request function

    Returns: (int: number of calls, float: time period)
    """
    clock = time.monotonic if hasattr(time, 'monotonic') else time.time

    start = clock()
    num_calls: int = 0

    try:
        async with asyncio.timeout(10 * 60):
            while True:
                if inspect.iscoroutinefunction(request_func):
                    rv = await request_func(*args, **kwargs)
                else:
                    rv = request_func(*args, **kwargs)
                num_calls += 1
                await asyncio.sleep(0.1)

                if hasattr(rv, 'status_code') or hasattr(rv, 'status'):
                    status_code = rv.status_code if hasattr(rv, 'status_code') else rv.status
                    if status_code == 429:
                        if hasattr(rv, 'headers'):
                            headers = rv.headers

                            if 'X-RateLimit-Limit' in headers:
                                limit = int(headers['X-RateLimit-Limit'])
                                period = float(headers['X-RateLimit-Reset-After'])
                                return limit, period + (clock() - start)
                            elif 'Retry-After' in headers:
                                period = float(headers['Retry-After']) + (clock() - start)
                                return num_calls - 1, period
                        else:
                            try:
                                reset_time = await _ping_for_200(request_func, *args, incremental_backoff, **kwargs)
                            except ValueError:
                                print("Could not determine the reset time for the given request function")
                                print("Total number of calls allowed per given time period is:", num_calls - 1)
                                raise
                            period = reset_time - start
                            return num_calls - 1, period
                else:
                    raise Exception(
                        "Cannot determine limit and period as the request function does not return a response object "
                        "with the 'status_code' or 'status' attribute."
                    )
    except asyncio.TimeoutError:
        print("Could not determine the reset time for the given request function")
        print(
            "This is probably because the given server/website has a very high rate limit (> 10 min period)")
        raise
