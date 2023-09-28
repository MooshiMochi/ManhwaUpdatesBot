"""
This is a test file for testing each scanlator class from scanlator.py

# Path: test.py
"""
from __future__ import annotations

import logging
import os
import sys
import traceback as tb
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from typing import Coroutine, Dict, Literal, Optional

from src.core.apis import ComickAppAPI, MangaDexAPI
from src.core.cache import CachedClientSession, CachedCurlCffiSession
from src.core.database import Database
from src.core.objects import Chapter, Manga
from src.core.scanlators import scanlators
from src.core.scanlators.classes import AbstractScanlator
from src.static import Constants
from src.utils import ensure_configs, load_config, setup_logging

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
        self.session = CachedClientSession(proxy=self.proxy_addr, name="cache.bot", trust_env=True)
        self.db = Database(self)  # noqa
        self.mangadex_api = MangaDexAPI(self.session)
        self.comick_api = ComickAppAPI(self.session)
        self._all_scanners: dict = scanlators.copy()  # You must not mutate this dict. Mutate SCANLATORS instead.
        self.load_scanlators(scanlators)
        self.user = User()

    def load_scanlators(self, _scanlators: dict):
        for scanlator in _scanlators.values():
            scanlator.bot = self
        self._all_scanners.update(_scanlators)

    async def async_init(self):
        await self.db.async_init()

    async def close(self):
        # await self.cf_scraper.close()
        await self.session.close()
        self.curl_session.close() if self.curl_session else None

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

        ip, port = proxy_dict.get("ip"), proxy_dict.get("port")
        if not ip or not port:
            return None

        if (user := proxy_dict.get("username")) and ([pwd := proxy_dict.get("password")]):
            return f"http://{user}:{pwd}@{ip}:{port}"
        else:
            return f"http://{ip}:{port}"


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
            last_3_chapter_urls: list[str]):
        self.scanlator_name: str = scanlator_name
        self.manga_url: str = manga_url.removesuffix("/")
        self.completed: bool = completed
        self.title: str = title
        self.manga_id: str | int = manga_id
        self.curr_chapter_url: str = curr_chapter_url.removesuffix("/")
        self.first_chapter_url: str = first_chapter_url.removesuffix("/")
        self.cover_image: str = cover_image.removesuffix("/")
        self.last_3_chapter_urls: list[str] = [x.removesuffix("/") for x in last_3_chapter_urls]

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
        evaluated: bool = result == self.expected_result.manga_url
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
            print(f"   ↳ Got: {manga.available_chapters[-3].url if len(manga.available_chapters) >= 3 else None}")
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
        print(result)
        return True

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
            (self.scanlator_name, "❌ Failed to match scanlator name to expected name")
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

    def setup(self):
        self.test = Test(self.test_setup, self.test_data, self.expected_result, self.test_subject, self.id_first)

    async def begin(self, test_method: str = "all") -> str:
        if self.test_subject is None or self.test_subject.name not in scanlators:
            print(f"Scanlator {self.test_subject} is disabled! No tests will be run.")
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
        self.testCases: dict[str, TestCase] = {
            "tritinia": TestCase(
                self.test_setup,
                test_data=TestInputData("https://tritinia.org/manga/momo-the-blood-taker/"),
                expected_result=ExpectedResult(
                    scanlator_name="tritinia",
                    manga_url="https://tritinia.org/manga/momo-the-blood-taker/",
                    completed=True,
                    title="MOMO: The Blood Taker",
                    manga_id=default_id_func("https://tritinia.org/manga/momo-the-blood-taker"),
                    curr_chapter_url="https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-48/",
                    first_chapter_url=(
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-1/ch-1-v-coming-soon-scans/"
                    ),
                    cover_image="https://tritinia.org/wp-content/uploads/2022/02/000.jpg",
                    last_3_chapter_urls=[
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-46/",
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-47/",
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-48/",
                    ]
                ),
                test_subject=scanlators.get("tritinia")
            ),
            "manganato": TestCase(
                self.test_setup,
                test_data=TestInputData("https://chapmanganato.com/manga-hf985162"),
                expected_result=ExpectedResult(
                    scanlator_name="manganato",
                    manga_url="https://chapmanganato.com/manga-hf985162/",
                    completed=False,
                    title="God Of Blackfield",  # noqa
                    manga_id="hf985162",
                    curr_chapter_url="https://chapmanganato.com/manga-hf985162/chapter-155",
                    first_chapter_url="https://chapmanganato.com/manga-hf985162/chapter-1",
                    cover_image="https://avt.mkklcdnv6temp.com/3/y/21-1587115897.jpg",
                    last_3_chapter_urls=[
                        "https://chapmanganato.com/manga-hf985162/chapter-153",
                        "https://chapmanganato.com/manga-hf985162/chapter-154",
                        "https://chapmanganato.com/manga-hf985162/chapter-155",
                    ]
                ),
                test_subject=scanlators.get("manganato"),
                id_first=True
            ),
            "toonily": TestCase(
                self.test_setup,
                test_data=TestInputData(
                    "https://toonily.com/webtoon/lucky-guy-0002/"
                ),
                expected_result=ExpectedResult(
                    scanlator_name="toonily",
                    manga_url="https://toonily.com/webtoon/lucky-guy-0002/",
                    completed=True,
                    title="Lucky Guy",
                    manga_id=default_id_func("https://toonily.com/webtoon/lucky-guy-0002"),
                    curr_chapter_url="https://toonily.com/webtoon/lucky-guy-0002/chapter-73/",
                    first_chapter_url="https://toonily.com/webtoon/lucky-guy-0002/chapter-1/",
                    cover_image=(
                        "https://toonily.com/wp-content/uploads/2020/02/Lucky-Guy.jpg"),
                    last_3_chapter_urls=[
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-71/",
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-72/",
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-73/",
                    ]
                ),
                test_subject=scanlators.get("toonily")
            ),
            "mangadex": TestCase(
                self.test_setup,
                test_data=TestInputData("https://mangadex.org/title/7dbeaa0e-420a-4dc0-b2d3-eb174de266da/zippy-ziggy"),
                expected_result=ExpectedResult(
                    scanlator_name="mangadex",
                    manga_url="https://mangadex.org/title/7dbeaa0e-420a-4dc0-b2d3-eb174de266da",
                    completed=True,
                    title="Zippy Ziggy",
                    manga_id="7dbeaa0e-420a-4dc0-b2d3-eb174de266da",
                    curr_chapter_url="https://mangadex.org/chapter/aef242d7-0051-431f-9f03-53442afdbead",
                    first_chapter_url="https://mangadex.org/chapter/388124f0-dc2e-43db-b19e-71d0e3eddfc6",
                    cover_image=(
                        "https://uploads.mangadex.org/covers/7dbeaa0e-420a-4dc0-b2d3-eb174de266da/192e6a85-80d5-42b4"
                        "-bdda-81b56592c44f.jpg"  # noqa
                    ),
                    last_3_chapter_urls=[
                        "https://mangadex.org/chapter/03402aaa-8eba-43ac-a83e-ce336c75aa62",
                        "https://mangadex.org/chapter/ee43a7c7-595a-4006-9dc0-df44b0f37b59",
                        "https://mangadex.org/chapter/aef242d7-0051-431f-9f03-53442afdbead",
                    ]
                ),
                test_subject=scanlators.get("mangadex"),
            ),
            "flamescans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://flamescans.org/series/1695679321-the-villainess-is-a-marionette/"),
                expected_result=ExpectedResult(
                    scanlator_name="flamescans",
                    manga_url="https://flamescans.org/series/1695679321-the-villainess-is-a-marionette/",
                    completed=True,
                    title="The Villainess is a Marionette",  # noqa
                    manga_id=default_id_func("https://flamescans.org/series/1695679321-the-villainess-is-a-marionette"),
                    curr_chapter_url="https://flamescans.org/1695679321-the-villainess-is-a-marionette-chapter-69/",
                    first_chapter_url="https://flamescans.org/1695679262-the-villainess-is-a-marionette-chapter-0/",
                    cover_image="https://flamescans.org/wp-content/uploads/2021/02/VIAM_S2_COVER.jpg",
                    last_3_chapter_urls=[
                        "https://flamescans.org/1695679262-the-villainess-is-a-marionette-chapter-67/",
                        "https://flamescans.org/1695679262-the-villainess-is-a-marionette-chapter-68/",
                        "https://flamescans.org/1695679262-the-villainess-is-a-marionette-chapter-69/",
                    ]
                ),
                test_subject=scanlators.get("flamescans")
            ),
            "asura": TestCase(
                self.test_setup,
                test_data=TestInputData("https://asuracomics.gg/manga/4102803034-i-regressed-as-the-duke/"),
                expected_result=ExpectedResult(
                    scanlator_name="asura",
                    manga_url="https://asuracomics.gg/manga/4102803034-i-regressed-as-the-duke/",
                    completed=True,
                    title="I Regressed As The Duke",
                    manga_id=default_id_func(
                        "https://asuracomics.gg/manga/4102803034-i-regressed-as-the-duke"
                    ),
                    curr_chapter_url="https://asuracomics.gg/5649036567-i-regressed-as-the-duke-chapter-64-notice/",
                    first_chapter_url="https://asuracomics.gg/5649036567-i-regressed-as-the-duke-chapter-1/",
                    cover_image="https://asuracomics.gg/wp-content/uploads/2022/04/unknown_1-1.png",
                    last_3_chapter_urls=[
                        "https://asuracomics.gg/5649036567-i-regressed-as-the-duke-chapter-62/",
                        "https://asuracomics.gg/5649036567-i-regressed-as-the-duke-chapter-63/",
                        "https://asuracomics.gg/5649036567-i-regressed-as-the-duke-chapter-64-notice/",
                    ]
                ),
                test_subject=scanlators.get("asura")
            ),
            "aquamanga": TestCase(
                self.test_setup,
                test_data=TestInputData("https://aquamanga.com/read/court-swordswoman-in-another-world/"),
                expected_result=ExpectedResult(
                    scanlator_name="aquamanga",
                    manga_url="https://aquamanga.com/read/court-swordswoman-in-another-world/",
                    completed=True,
                    title="Court Swordswoman in Another World",  # noqa
                    manga_id=default_id_func("https://aquamanga.com/read/court-swordswoman-in-another-world"),
                    curr_chapter_url="https://aquamanga.com/read/court-swordswoman-in-another-world/chapter-15/",
                    first_chapter_url="https://aquamanga.com/read/court-swordswoman-in-another-world/chapter-1/",
                    cover_image=(
                        "https://aquamanga.com/wp-content/uploads/2021/03/court-swordswoman-in-another-world.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://aquamanga.com/read/court-swordswoman-in-another-world/chapter-13/",
                        "https://aquamanga.com/read/court-swordswoman-in-another-world/chapter-14/",
                        "https://aquamanga.com/read/court-swordswoman-in-another-world/chapter-15/",
                    ]
                ),
                test_subject=scanlators.get("aquamanga")
            ),
            "reaperscans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://reaperscans.com/comics/4099-the-legendary-mechanic"),
                expected_result=ExpectedResult(
                    scanlator_name="reaperscans",
                    manga_url="https://reaperscans.com/comics/4099-the-legendary-mechanic",
                    completed=True,
                    title="The Legendary Mechanic",
                    manga_id="4099",
                    curr_chapter_url=(
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/22619310-chapter-10"
                    ),
                    first_chapter_url=(
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/24239107-chapter-0"
                    ),
                    cover_image=(
                        "https://media.reaperscans.com/file/4SRBHm/comics/167d3d48-6d3a-4af3-9e04-183c28938df8"
                        "/NnJgo5uCLKDisl2OSBtbBKDbZYdqUeeeGjH8qoh2.jpg"  # noqa
                    ),
                    last_3_chapter_urls=[
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/56469949-chapter-8",
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/11904616-chapter-9",
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/22619310-chapter-10",
                    ],
                ),
                id_first=True,
                test_subject=scanlators.get("reaperscans"),
            ),
            "anigliscans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://anigliscans.xyz/series/blooming/"),
                expected_result=ExpectedResult(
                    scanlator_name="anigliscans",
                    manga_url="https://anigliscans.xyz/series/blooming/",
                    completed=True,
                    title="BLOOMING",
                    manga_id=default_id_func("https://anigliscans.xyz/series/blooming"),
                    curr_chapter_url="https://anigliscans.xyz/blooming-chapter-24/",
                    first_chapter_url="https://anigliscans.xyz/blooming-chapter-1/",
                    cover_image="https://anigliscans.xyz/wp-content/uploads/2022/07/blooming_cov.png",
                    last_3_chapter_urls=[
                        "https://anigliscans.xyz/blooming-chapter-22/",
                        "https://anigliscans.xyz/blooming-chapter-23/",
                        "https://anigliscans.xyz/blooming-chapter-24/",
                    ],
                ),
                test_subject=scanlators.get("anigliscans")
            ),
            "comick": TestCase(
                self.test_setup,
                test_data=TestInputData("https://comick.app/comic/00-solo-leveling?lang=en"),
                expected_result=ExpectedResult(
                    scanlator_name="comick",
                    manga_url="https://comick.app/comic/00-solo-leveling?lang=en",
                    completed=True,
                    title="Solo Leveling",
                    manga_id="71gMd0vF",
                    curr_chapter_url="https://comick.app/comic/00-solo-leveling/DARIhC3K",
                    first_chapter_url="https://comick.app/comic/00-solo-leveling/P_ysNE3VbnLbwN",
                    cover_image="https://meo.comick.pictures/0GRgd.jpg",
                    last_3_chapter_urls=[
                        "https://comick.app/comic/00-solo-leveling/s_ukimbV",
                        "https://comick.app/comic/00-solo-leveling/YgUzmswO",
                        "https://comick.app/comic/00-solo-leveling/DARIhC3K",
                    ],
                ),
                test_subject=scanlators.get("comick")
            ),
            "voidscans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://void-scans.com/manga/superhuman-era/"),
                expected_result=ExpectedResult(
                    scanlator_name="voidscans",
                    manga_url="https://void-scans.com/manga/superhuman-era/",
                    completed=False,
                    title="Superhuman Era",
                    manga_id=default_id_func("https://void-scans.com/manga/superhuman-era"),
                    curr_chapter_url="https://void-scans.com/superhuman-era-chapter-48/",
                    first_chapter_url="https://void-scans.com/superhuman-era-chapter-0/",
                    cover_image="https://void-scans.com/wp-content/uploads/25-1638290924.jpg",
                    last_3_chapter_urls=[
                        "https://void-scans.com/superhuman-era-chapter-46/",
                        "https://void-scans.com/superhuman-era-chapter-47/",
                        "https://void-scans.com/superhuman-era-chapter-48/",
                    ],
                ),
                test_subject=scanlators.get("voidscans")
            ),
            "luminousscans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://luminousscans.com/series/1694588401-my-office-noonas-story/"),
                expected_result=ExpectedResult(
                    scanlator_name="luminousscans",
                    manga_url="https://luminousscans.com/series/1694588401-my-office-noonas-story/",
                    completed=True,
                    title="My Office Noona’s Story",  # noqa
                    manga_id=default_id_func("https://luminousscans.com/series/1694156401-my-office-noonas-story"),
                    curr_chapter_url="https://luminousscans.com/1694588401-my-office-noonas-story-epilogue-chapter-03/",
                    first_chapter_url="https://luminousscans.com/1694588401-my-office-noonas-story-prologue/",
                    cover_image=(
                        "https://luminousscans.com/wp-content/uploads/2021/05/My_Office_Noona_Story_Title-1.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://luminousscans.com/1694588401-my-office-noonas-story-epilogue-chapter-01/",
                        "https://luminousscans.com/1694588401-my-office-noonas-story-epilogue-chapter-02/",
                        "https://luminousscans.com/1694588401-my-office-noonas-story-epilogue-chapter-03/",
                    ],
                ),
                id_first=True,
                test_subject=scanlators.get("luminousscans")
            ),
            "lscomic": TestCase(
                self.test_setup,
                test_data=TestInputData("https://lscomic.com/manga/8th-class-mage-returns/"),
                expected_result=ExpectedResult(
                    scanlator_name="lscomic",
                    manga_url="https://lscomic.com/manga/8th-class-mage-returns/",
                    completed=False,
                    title="8th-Class Mage Returns",
                    manga_id=default_id_func("https://lscomic.com/manga/8th-class-mage-returns"),
                    curr_chapter_url="https://lscomic.com/manga/8th-class-mage-returns/chapter-81/",
                    first_chapter_url="https://lscomic.com/manga/8th-class-mage-returns/chapter-1/",
                    cover_image="https://lscomic.com/wp-content/uploads/2023/09/cover-8CMR.png",
                    last_3_chapter_urls=[
                        "https://lscomic.com/manga/8th-class-mage-returns/chapter-79/",
                        "https://lscomic.com/manga/8th-class-mage-returns/chapter-80/",
                        "https://lscomic.com/manga/8th-class-mage-returns/chapter-81/",
                    ],
                ),
                test_subject=scanlators.get("lscomic")
            ),
            "drakescans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://drakescans.com/series/spirit-pet-creation-simulator1/"),
                expected_result=ExpectedResult(
                    scanlator_name="drakescans",
                    manga_url="https://drakescans.com/series/spirit-pet-creation-simulator1/",
                    completed=True,
                    title="Spirit Pet Creation Simulator",
                    manga_id=default_id_func("https://drakescans.com/series/spirit-pet-creation-simulator1"),
                    curr_chapter_url="https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-28/",
                    first_chapter_url="https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-00/",
                    cover_image="https://i0.wp.com/drakescans.com/wp-content/uploads/2022/02/01.jpg",
                    last_3_chapter_urls=[
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-26/",
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-27/",
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-28/",
                    ],
                ),
                test_subject=scanlators.get("drakescans")
            ),
            "mangabaz": TestCase(
                self.test_setup,
                test_data=TestInputData("https://mangabaz.net/mangas/i-grow-stronger-by-eating/"),
                expected_result=ExpectedResult(
                    scanlator_name="mangabaz",
                    manga_url="https://mangabaz.net/mangas/i-grow-stronger-by-eating/",
                    completed=False,
                    title="I Grow Stronger By Eating!",
                    manga_id=default_id_func("https://mangabaz.net/mangas/i-grow-stronger-by-eating"),
                    curr_chapter_url="https://mangabaz.net/mangas/i-grow-stronger-by-eating/chapter-100/",
                    first_chapter_url="https://mangabaz.net/mangas/i-grow-stronger-by-eating/chapter-1/",
                    cover_image=(
                        "https://mangabaz.net/wp-content/uploads/2023/03/I-Grow-Stronger-By-Eating.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://mangabaz.net/mangas/i-grow-stronger-by-eating/chapter-98/",
                        "https://mangabaz.net/mangas/i-grow-stronger-by-eating/chapter-99/",
                        "https://mangabaz.net/mangas/i-grow-stronger-by-eating/chapter-100/",
                    ],
                ),
                test_subject=scanlators.get("mangabaz")
            ),
            "mangapill": TestCase(
                self.test_setup,
                test_data=TestInputData("https://mangapill.com/manga/57/3d-kanojo"),
                expected_result=ExpectedResult(
                    scanlator_name="mangapill",
                    manga_url="https://mangapill.com/manga/57/3d-kanojo",
                    completed=True,
                    title="3D Kanojo",
                    manga_id="57",
                    curr_chapter_url="https://mangapill.com/chapters/57-10047000/3d-kanojo-chapter-47",
                    first_chapter_url="https://mangapill.com/chapters/57-10001000/3d-kanojo-chapter-1",
                    cover_image="https://cdn.readdetectiveconan.com/file/mangapill/i/57.jpeg",
                    last_3_chapter_urls=[
                        "https://mangapill.com/chapters/57-10045000/3d-kanojo-chapter-45",
                        "https://mangapill.com/chapters/57-10046000/3d-kanojo-chapter-46",
                        "https://mangapill.com/chapters/57-10047000/3d-kanojo-chapter-47",
                    ],
                ),
                id_first=True,
                test_subject=scanlators.get("mangapill")
            ),
            "bato.to": TestCase(
                self.test_setup,
                test_data=TestInputData("https://bato.to/series/95400/queen-in-the-shadows"),
                expected_result=ExpectedResult(
                    scanlator_name="bato",
                    manga_url="https://bato.to/series/95400/queen-in-the-shadows",
                    completed=True,
                    title="Queen in the Shadows",
                    manga_id="95400",
                    curr_chapter_url="https://bato.to/chapter/2031007",
                    first_chapter_url="https://bato.to/chapter/1803219",
                    cover_image=(
                        "https://xfs-s118.batcg.org/thumb/W600/ampi/515"
                        "/5153a1fcfcfd904decc8777384a7e5511c195a09_400_600_65091.jpeg"  # noqa
                    ),
                    last_3_chapter_urls=[
                        "https://bato.to/chapter/2018714",
                        "https://bato.to/chapter/2029629",
                        "https://bato.to/chapter/2031007",
                    ],
                ),
                id_first=True,
                test_subject=scanlators.get("bato")
            ),
            "omegascans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://omegascans.org/series/dorm-room-sisters"),
                expected_result=ExpectedResult(
                    scanlator_name="omegascans",
                    manga_url="https://omegascans.org/series/dorm-room-sisters",
                    completed=False,
                    title="Dorm Room Sisters",
                    manga_id=default_id_func("https://omegascans.org/series/dorm-room-sisters"),
                    curr_chapter_url="https://omegascans.org/series/dorm-room-sisters/chapter-93-5",
                    first_chapter_url="https://omegascans.org/series/dorm-room-sisters/chapter-1",
                    cover_image=(
                        "https://media.omegascans.org/file/zFSsXt/covers/12333c4d-d82c-4a88-8b55-7f5e5f266457.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://omegascans.org/series/dorm-room-sisters/chapter-92",
                        "https://omegascans.org/series/dorm-room-sisters/chapter-93",
                        "https://omegascans.org/series/dorm-room-sisters/chapter-93-5",
                    ],
                ),
                test_subject=scanlators.get("omegascans")
            ),
            "nightscans": TestCase(
                self.test_setup,
                test_data=TestInputData("https://nightscans.net/series/all-attributes-in-martial-arts/"),
                expected_result=ExpectedResult(
                    scanlator_name="nightscans",
                    manga_url="https://nightscans.net/series/all-attributes-in-martial-arts",
                    completed=True,
                    title="All-Attributes in Martial Arts",  # noqa
                    manga_id=default_id_func("https://nightscans.net/series/all-attributes-in-martial-arts"),
                    curr_chapter_url="https://nightscans.net/all-attribute-in-martial-arts-chapter-70/",
                    first_chapter_url="https://nightscans.net/all-attribute-martial-arts-00/",
                    cover_image="https://nightscans.net/wp-content/uploads/2023/03/AAAMAcover_result.webp",
                    last_3_chapter_urls=[
                        "https://nightscans.net/all-attribute-in-martial-arts-chapter-68/",
                        "https://nightscans.net/all-attribute-in-martial-arts-chapter-69/",
                        "https://nightscans.net/all-attribute-in-martial-arts-chapter-70/",
                    ]
                ),
                test_subject=scanlators.get("nightscans")
            ),
            "suryascans": TestCase(  # noqa
                self.test_setup,
                test_data=TestInputData("https://suryascans.com/manga/modern-dude-in-the-murim/"),
                expected_result=ExpectedResult(
                    scanlator_name="suryascans",  # noqa
                    manga_url="https://suryascans.com/manga/modern-dude-in-the-murim",
                    completed=False,
                    title="Modern Dude in the Murim",  # noqa
                    manga_id=default_id_func("https://suryascans.com/manga/modern-dude-in-the-murim"),
                    curr_chapter_url="https://suryascans.com/modern-dude-in-the-murim-chapter-22/",
                    first_chapter_url="https://suryascans.com/modern-dude-in-the-murim-chapter-1/",
                    cover_image="https://suryascans.com/wp-content/uploads/2022/12/moden-guy-murim.webp",
                    last_3_chapter_urls=[
                        "https://suryascans.com/modern-dude-in-the-murim-chapter-20/",
                        "https://suryascans.com/modern-dude-in-the-murim-chapter-21/",
                        "https://suryascans.com/modern-dude-in-the-murim-chapter-22/",
                    ]
                ),
                test_subject=scanlators.get("suryascans")
            ),
        }

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
        tests_to_ignore = []
        await run_tests(testCases, tests_to_ignore)


async def sub_main():
    test_setup = SetupTest()
    await test_setup.bot.async_init()

    testCase = TestCase(
        test_setup,
        test_data=TestInputData("https://omegascans.org/series/fucked-the-world-tree"),
        expected_result=ExpectedResult(
            scanlator_name="omegascans",
            manga_url="https://omegascans.org/series/fucked-the-world-tree",
            completed=False,
            title="Fucked the World Tree",
            manga_id=default_id_func("https://omegascans.org/series/fucked-the-world-tree"),
            curr_chapter_url=(
                "https://omegascans.org/series/fucked-the-world-tree/chapter-14"
            ),
            first_chapter_url=(
                "https://omegascans.org/series/fucked-the-world-tree/chapter-1"
            ),
            cover_image=(
                "https://media.omegascans.org/file/zFSsXt/covers/adc97b9d-8fe1-49e0-95a1-494efbe32e7e.jpg"
            ),
            last_3_chapter_urls=[
                "https://omegascans.org/series/fucked-the-world-tree/chapter-12",
                "https://omegascans.org/series/fucked-the-world-tree/chapter-13",
                "https://omegascans.org/series/fucked-the-world-tree/chapter-14",
            ],
        ),
        # id_first=True,
        test_subject=scanlators.get("omegascans")
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


async def test_single_method(scanlator: str, test_method: Literal[
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
]):
    async with TestCases() as testCases:
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
    db_filepath: str = "./database.db"
    if os.path.exists(db_filepath):
        os.remove(db_filepath)

    if os.name != "nt":
        asyncio.run(main())
    else:
        asyncio.run(main())
        # asyncio.run(sub_main())
        # asyncio.run(paused_test())
        # asyncio.run(test_single_method("reaperscans", "first_chapter_url"))
        # asyncio.run(test_single_scanlator("reaperscans"))
