"""
This is a test file for testing each scanlator class from scanlator.py

# Path: test.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback as tb
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from typing import Coroutine, Dict, Literal, Optional

import aiohttp
import requests  # noqa

from src.core.apis import APIManager
from src.core.cache import CachedClientSession, CachedCurlCffiSession
from src.core.config_loader import ensure_configs, load_config
from src.core.database import Database
from src.core.objects import Chapter, Manga
from src.core.scanlators import scanlators
from src.core.scanlators.classes import AbstractScanlator
from src.enums import Minutes
from src.static import Constants
from src.utils import setup_logging

logger: logging.Logger = logging.getLogger("test")

root_path = [x for x in sys.path if x.removesuffix("/").endswith("ManhwaUpdatesBot")][0]


# noinspection PyTypeChecker

class _ThirdProperties:
    url = ""


class User:
    @property
    def display_avatar(self):
        return _ThirdProperties()

    @property
    def display_name(self):
        return "Manhwa Updates"


class Bot:
    def __init__(self, config: Dict):
        self.config: Dict = config
        self.logger = logging.getLogger("test.bot")
        self.proxy_addr = self._fmt_proxy()
        self.curl_session = CachedCurlCffiSession(impersonate="chrome101", name="cache.curl_cffi", proxies={
            "http": self.proxy_addr,
            "https": self.proxy_addr
        })
        session_timeout = aiohttp.ClientTimeout(total=Minutes.FIVE.value)  # 5 min
        self.session = CachedClientSession(
            proxy=self.proxy_addr, name="cache.bot", trust_env=True, timeout=session_timeout
        )
        self.db = Database(self)  # noqa
        self.apis: APIManager = APIManager(
            self, CachedClientSession(  # noqa
                proxy=self.proxy_addr, name="cache.apis", trust_env=True, timeout=session_timeout
            )
        )
        self._all_scanners: dict = scanlators.copy()  # You must not mutate this dict. Mutate SCANLATORS instead.
        self.load_scanlators(scanlators)
        self.user = User()

    def load_scanlators(self, _scanlators: dict):
        for scanlator in _scanlators.values():
            scanlator.bot = self
        self._all_scanners.update(_scanlators)

    async def async_init(self):
        await self.db.async_init()
        await self.apis.webshare.async_init()
        if self.apis.webshare.is_available:
            self.apis.flare.proxy = (await self.apis.webshare.get_proxy()).to_url_dict()
        await self.apis.flare.async_init()

        if not self.apis.flare.is_available:
            self.logger.error("FlareSolverr is not available. Using curl_cffi instead of flare.")
            for scanner in scanlators.keys():
                if scanlators[scanner].json_tree.request_method == "flare":
                    scanlators[scanner].json_tree.request_method = "curl"

    async def close(self):
        # await self.cf_scraper.close()
        self.logger.info("Closing test instance...")

        self.curl_session.close() if self.curl_session else None
        if self.apis.flare.is_available:
            self.logger.info("[FlareSolverr] > Begin server session cleanup...")
            await self.apis.flare.get_active_sessions()  # refresh the session cache just to be safe
            await self.apis.flare.destroy_all_sessions()  # destroy all active sessions
            self.logger.info("[FlareSolverr] > Server session cleanup complete.")

        self.logger.info("Closing aiohttp sessions...")
        await self.session.close()
        await self.apis.session.close()
        self.logger.info("Aiohttp sessions closed.")
        if self.curl_session:
            self.logger.info("Closing curl session...")
            try:
                await self.curl_session.close()
                self.logger.info("Curl session closed.")
            except TypeError:
                self.logger.warning("Skipping curl session close due to TypeError.")
        self.logger.info("Finalising closing procedure! Goodbye!")

    async def __aenter__(self):
        await self.db.async_init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @staticmethod
    async def log_to_discord(message, **kwargs):
        print(message, kwargs)

    def _fmt_proxy(self) -> Optional[str]:
        proxy_dict = self.config.get("proxy")
        if proxy_dict is None or proxy_dict.get("enabled") is False:
            return None

        if os.name != "nt":  # disable proxy on non-windows systems
            self.config["proxy"]["enabled"] = False
            return None

        ip, port = proxy_dict.get("proxy_address"), proxy_dict.get("port")
        if not ip or not port:
            return None

        if (user := proxy_dict.get("username")) and ([pwd := proxy_dict.get("password")]):
            return f"http://{user}:{pwd}@{ip}:{port}"  # noqa
        else:
            return f"http://{ip}:{port}"  # noqa


class SetupTest:
    def __init__(self):
        self.bot: Bot = Bot(self.load_config())
        self.bot.load_scanlators(scanlators)

    @staticmethod
    def load_config() -> Dict:
        config = load_config(logger, auto_exit=False, filepath=os.path.join(root_path, "tests/config.yml"))
        return ensure_configs(logger, config, scanlators, auto_exit=False)


class ExpectedResult:
    def __init__(
            self,
            scanlator_name: str,
            manga_url: str,
            completed: bool,
            title: str,
            manga_id: str | int | Coroutine,
            curr_chapter_url: str,
            first_chapter_url: str,
            cover_image: str,
            last_3_chapter_urls: list[str],
            has_fp_manhwa: bool = False
    ):
        self.scanlator_name: str = scanlator_name
        self.manga_url: str = manga_url.removesuffix("/")
        self.completed: bool = completed
        self.title: str = title
        self.manga_id: str | int = manga_id
        self.curr_chapter_url: str = curr_chapter_url.removesuffix("/")
        self.first_chapter_url: str = first_chapter_url.removesuffix("/")
        self.cover_image: str = cover_image.removesuffix("/")
        self.last_3_chapter_urls: list[str] = [x.removesuffix("/") for x in last_3_chapter_urls]
        self.has_fp_manhwa: bool = has_fp_manhwa

        if len(self.last_3_chapter_urls) != 3:
            raise ValueError(f"[{scanlator_name}] Expected 3 chapter urls, got {len(self.last_3_chapter_urls)}")

    def extract_last_read_chapter(self, manga: Manga) -> Optional[Chapter]:
        for chapter in manga.available_chapters:
            if chapter.url.removesuffix("/") == self.last_3_chapter_urls[0].removesuffix("/"):
                return chapter
        return None


class TestInputData:
    def __init__(self, manga_url: str):
        self.manga_url: str = manga_url


# noinspection PyTypeChecker
class Test:
    def __init__(
            self,
            test_setup: SetupTest,
            test_data: TestInputData,
            expected_result: ExpectedResult,
            test_subject: AbstractScanlator,
            id_first: bool = False
    ):
        self.test_subject: AbstractScanlator = test_subject
        self.test_data: TestInputData = test_data
        self.expected_result: ExpectedResult = expected_result
        self.setup_test = test_setup
        self._bot: Bot = self.setup_test.bot
        self.id_first: bool = id_first

        self.manga_id: str | int | None = None
        self.fmt_url: str | None = None

    async def fmt_manga_url(self) -> bool:
        result = await self.test_subject.format_manga_url(self.test_data.manga_url)
        result = result.removesuffix("/")
        self.fmt_url = result
        evaluated: bool = result.removesuffix("/") == self.expected_result.manga_url
        if not evaluated:
            print(f"Expected: {self.expected_result.manga_url}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def get_manga_id(self) -> bool:
        result = await self.test_subject.get_id(raw_url=(self.fmt_url or self.test_data.manga_url))
        self.manga_id = result
        evaluated: bool = result == self.expected_result.manga_id
        if not evaluated:
            print(f"Expected: {self.expected_result.manga_id}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def is_completed(self) -> bool:
        result = await self.test_subject.get_status(self.fmt_url)
        result = result.lower() in Constants.completed_status_set
        evaluated: bool = result == self.expected_result.completed
        if not evaluated:
            print(f"Expected: {self.expected_result.completed}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def title(self) -> bool:
        result = await self.test_subject.get_title(self.fmt_url)
        evaluated: bool = result == self.expected_result.title
        if not evaluated:
            print(f"Expected: {self.expected_result.title}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def first_chapter_url(self) -> bool:
        result = await self.test_subject.get_all_chapters(self.fmt_url)
        evaluated: bool = (
                result is not None and result[0].url.removesuffix(
            "/"  # noqa
        ) == self.expected_result.first_chapter_url.removesuffix("/")
        )
        if not evaluated:
            print(f"Expected: {self.expected_result.first_chapter_url.removesuffix('/')}")
            print(f"   ↳ Got: {result[0].url.removesuffix('/')}")
        return evaluated

    async def cover_image(self) -> bool:
        result = await self.test_subject.get_cover(self.fmt_url)
        result = result.split("?")[0].rstrip("/")  # remove URL params
        evaluated: bool = result == self.expected_result.cover_image
        if not evaluated:
            print(f"Expected: {self.expected_result.cover_image}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def check_updates(self) -> bool:
        # As long as the previous tests pass, the make_manga_object method should automatically pass
        manga = await self.test_subject.make_manga_object(self.fmt_url)
        # get the last read chapter where the url == last_3_chapter_urls[0]
        last_read_chapter = self.expected_result.extract_last_read_chapter(manga)
        if not last_read_chapter:
            print(f"Expected: {self.expected_result.last_3_chapter_urls[0]}")
            print(
                f"   ↳ Got: {manga.available_chapters[-3].url.removesuffix('/') if len(manga.available_chapters) >= 3 else None}")  # noqa
            raise AssertionError("❌ Last 3 chapter urls at index 0 does not match any chapter in the manga object")
        manga._last_chapter = last_read_chapter
        result = await self.test_subject.check_updates(manga)
        evaluated: bool = all(
            [
                result.new_chapters[i].url.rstrip("/") == (self.expected_result.last_3_chapter_urls[-2:][i].rstrip("/"))
                for i in range(2)
            ]
        )
        if not evaluated:
            for i in range(2):
                print(f"Expected: {self.expected_result.last_3_chapter_urls[-2:][i]}")
                print(f"   ↳ Got: {result.new_chapters[i].url}")
        return evaluated

    async def show_synopsis(self) -> bool:
        result = await self.test_subject.get_synopsis(self.fmt_url)
        print(result)
        return result is not None and result.strip() != ""

    async def show_front_page_results(self) -> bool:
        result = await self.test_subject.get_fp_partial_manga()
        return not self.expected_result.has_fp_manhwa or (result is not None and len(result) > 0)

    def scanlator_name(self) -> bool:
        evaluated: bool = self.test_subject.name == self.expected_result.scanlator_name
        if not evaluated:
            print(f"Expected: {self.expected_result.scanlator_name}")
            print(f"   ↳ Got: {self.test_subject.name}")
        return evaluated

    async def begin(self, test_method: str = "all") -> str:
        checks_passed: int = 0
        print(f"🔎 [{self.expected_result.scanlator_name}] Running tests...")
        checks_to_run: list[tuple[callable, str]] = [
            (self.get_manga_id, "❌ Failed to get manga id"),
            (self.fmt_manga_url, "❌ Failed to format manga url"),
            (self.is_completed, "❌ Failed to get completed status"),
            (self.title, "❌ Failed to get title"),
            (self.first_chapter_url, "❌ Failed to get first chapter url"),
            (self.cover_image, "❌ Failed to get cover image"),
            (self.check_updates, "❌ Failed to check for updates"),
            (self.scanlator_name, "❌ Failed to match scanlator name to expected name"),
            (self.show_front_page_results, "❌ Failed to get front page results"),
        ]
        if not self.id_first:
            checks_to_run[0], checks_to_run[1] = checks_to_run[1], checks_to_run[0]

        single_test_methods = ["show_synopsis", "show_front_page_results"]
        if test_method != "all":
            if test_method not in single_test_methods:
                method_to_test = [check for check in checks_to_run if check[0].__name__ == test_method]
                if not method_to_test:
                    print(f"❌ [{self.expected_result.scanlator_name}] No test method named {test_method}")
                    print("Available test methods:")
                    print("\n".join([check[0].__name__ for check in checks_to_run]))
                checks_to_run = checks_to_run[:2]
                checks_to_run.extend(method_to_test)
            else:
                single_checks = [
                    (self.show_synopsis, "❌ Failed to get synopsis"),
                    (self.show_front_page_results, "❌ Failed to get front page results")
                ]
                checks_to_run = [
                    (self.get_manga_id, "❌ Failed to get manga id"),
                    (self.fmt_manga_url, "❌ Failed to format manga url"),
                ]
                checks_to_run.extend([check for check in single_checks if check[0].__name__ == test_method])

        for check, error_msg in checks_to_run:
            try:
                if iscoroutinefunction(check):
                    result = await check()
                else:
                    result = check()
                assert result, error_msg
                checks_passed += 1
            except AssertionError as e:
                print(e)
            except requests.exceptions.HTTPError as e:
                print(f"{error_msg}: {e.response.status_code} {e.response.reason}")
            except Exception as e:
                print(f"❌ Unexpected error: {e} --- {error_msg}")
                exc = tb.format_exception(type(e), e, e.__traceback__)
                print("".join(exc))
        emoji = "❌" if checks_passed != len(checks_to_run) else "✅"
        print(f"{emoji} [{self.expected_result.scanlator_name}] Passed {checks_passed}/{len(checks_to_run)} tests")
        return f"{checks_passed}/{len(checks_to_run)}"


@dataclass
class TestCase:
    test_setup: SetupTest
    test_data: TestInputData
    expected_result: ExpectedResult
    test_subject: AbstractScanlator
    test: Test | None = None
    id_first: bool = False
    has_fp_manhwa: bool = False

    def setup(self):
        self.test = Test(self.test_setup, self.test_data, self.expected_result, self.test_subject, self.id_first)

    async def begin(self, test_method: str = "all") -> str:
        if self.test_subject is None or self.test_subject.name not in scanlators:
            print(f"⚠️ Scanlator {self.test_subject} is disabled! No tests will be run.")
            return "N/A"
        else:
            return await self.test.begin(test_method)


async def default_id_func(manga_url: str) -> str:
    for scan in scanlators.values():
        if scan.check_ownership(manga_url):
            return await scan.get_id(manga_url)


async def run_tests(test_cases: dict[str, TestCase], to_ignore: list[str] = None):
    successful_tests = 0
    total_tests = len(test_cases)
    for scanlator_name in scanlators.keys():
        if scanlator_name not in test_cases:
            print(f"⚠️ Scanlator {scanlator_name} does not have a test case!")
        elif scanlator_name in to_ignore:
            print(f"⚠️ Scanlator {scanlator_name} is disabled! No tests will be run.")
    if to_ignore is None:
        to_ignore = []
    for name, test_case in test_cases.items():
        if name in to_ignore:
            total_tests -= 1
            continue

        test_case.setup()
        checks_passed: str = await test_case.begin()
        if checks_passed == "N/A":
            total_tests -= 1
            continue

        passed_of_total = checks_passed.split("/")
        if passed_of_total[0] == passed_of_total[1]:
            successful_tests += 1

    if successful_tests == total_tests:
        print("🎉 All tests passed!")
    else:
        print(f"❌ {total_tests - successful_tests}/{total_tests} tests failed!")


async def run_single_test(test_case: TestCase, test_method: str = "all"):
    test_case.setup()
    await test_case.begin(test_method)


class TestCases(dict):
    def __init__(self):
        self.test_setup = SetupTest()

        with open(os.path.join(root_path, "tests/test_map.json"), "r", encoding="utf-8") as f:
            test_map = json.load(f)
        self.testCases: dict[str, TestCase] = {}
        for scanlator_name, test_data in test_map.items():
            if scanlator_name not in scanlators:
                print(f"⚠️ Scanlator {scanlator_name} is disabled! No tests will be run.")
                continue
            expected_resutls = test_data["expected_results"]
            self.testCases[scanlator_name] = TestCase(
                self.test_setup,
                test_data=TestInputData(test_data["user_input_url"]),
                expected_result=ExpectedResult(
                    scanlator_name=expected_resutls["scanlator_name"],
                    manga_url=expected_resutls["manga_url"],
                    completed=expected_resutls["completed"],
                    title=expected_resutls["title"],
                    manga_id=(
                        default_id_func(expected_resutls["manga_url"])
                        if expected_resutls["use_default_id_function"] is True
                        else expected_resutls["manga_id"]
                    ),
                    curr_chapter_url=expected_resutls["curr_chapter_url"],
                    first_chapter_url=expected_resutls["first_chapter_url"],
                    cover_image=expected_resutls["cover_image"],
                    last_3_chapter_urls=expected_resutls["last_3_chapter_urls"],
                    has_fp_manhwa=expected_resutls.get("has_fp_manhwa", False)
                ),
                test_subject=scanlators.get(scanlator_name)
            )
        super().__init__(**self.testCases)

    async def __aenter__(self):
        await self.test_setup.bot.async_init()
        for name, klass in self.testCases.items():
            if isinstance(klass.expected_result.manga_id, Coroutine):
                klass.expected_result.manga_id = await klass.expected_result.manga_id
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.test_setup.bot.close()


async def main():
    async with TestCases() as testCases:
        tests_to_ignore = ["asura", "luminousscans", "rizzcomic", "reaperscans", "manhwa-freak"]
        # "voidscans", "astrascans", "reaperscans"
        await run_tests(testCases, tests_to_ignore)


async def sub_main():
    test_setup = SetupTest()
    await test_setup.bot.async_init()

    testCase = TestCase(
        test_setup,
        test_data=TestInputData("https://bato.to/series/114456"),
        expected_result=ExpectedResult(
            scanlator_name="bato",
            manga_url="https://bato.to/series/114456",
            completed=False,
            title="𝑻𝒉𝒆 𝒏𝒐𝒓𝒕𝒉𝒆𝒓𝒏 𝒅𝒖𝒌𝒆 𝒏𝒆𝒆𝒅𝒔 𝒂 𝒘𝒂𝒓𝒎 𝒉𝒖𝒈",
            manga_id="114456",
            curr_chapter_url='https://bato.to/chapter/2604874',
            first_chapter_url='https://bato.to/chapter/2106083',
            cover_image='https://xfs-s100.batcg.org/thumb/W600/ampi/b34'
                        '/b3407172605fe7cb934c0a90a6fc477b2e6110c6_720_1508_200588.jpeg',
            last_3_chapter_urls=[
                "https://bato.to/chapter/2603775",
                "https://bato.to/chapter/2604873",
                "https://bato.to/chapter/2604874"
            ],
        ),
        # id_first=True,
        test_subject=scanlators.get("bato")
    )
    try:
        await run_single_test(testCase)
    finally:
        await test_setup.bot.close()


async def paused_test():
    async with TestCases() as testCases:
        for scanner, testCase in testCases.items():
            await run_single_test(testCase)
            input("Press Enter to continue...")

        print("Testing finished!")


async def test_single_method(test_method: Literal[
    "fmt_manga_url",
    "get_manga_id",
    "is_completed",
    "title",
    "first_chapter_url",
    "cover_image",
    "check_updates",
    "scanlator_name",
    "show_synopsis",
    "show_front_page_results"
], scanlator: str | None = None):
    async with TestCases() as testCases:
        if scanlator is None:
            for scanlator in scanlators:
                await run_single_test(testCases[scanlator], test_method=test_method)
        else:
            await run_single_test(testCases[scanlator], test_method=test_method)


async def test_single_scanlator(scanlator: str):
    async with TestCases() as testCases:
        await run_single_test(testCases[scanlator])


if __name__ == "__main__":
    import asyncio
    import sys

    if sys.version_info >= (3, 8) and sys.platform.lower().startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_logging(level=logging.INFO)

    # delete the database file in the ./tests file before proceeding with the tests
    db_filepath: str = os.path.join(root_path, "tests/database.db")
    if os.path.exists(db_filepath):
        os.remove(db_filepath)

    if os.name != "nt":
        asyncio.run(main())
    else:
        # asyncio.run(test_single_method("show_front_page_results", "mangabat"))
        asyncio.run(test_single_scanlator("asura"))
        # asyncio.run(sub_main())
        # asyncio.run(paused_test())
        # asyncio.run(main())
