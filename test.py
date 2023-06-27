"""
This is a test file for testing each individual scanlator class from scanlator.py

# Path: test.py
"""
from __future__ import annotations

import hashlib
import logging
import os
import traceback as tb
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from typing import Dict, Optional, Type

from src.core.cache import CachedClientSession, CachedCurlCffiSession
from src.core.comickAPI import ComickAppAPI
from src.core.database import Database
from src.core.mangadexAPI import MangaDexAPI
from src.core.scanners import *
from src.core.scanners import SCANLATORS
from src.utils import ensure_configs, load_config

logger: logging.Logger = logging.getLogger("test")


# noinspection PyTypeChecker
class Bot:
    def __init__(self, config: Dict):
        self.config: Dict = config
        self.proxy_addr = self._fmt_proxy()
        self.curl_session = CachedCurlCffiSession(impersonate="chrome101", name="cache.curl_cffi", proxies={
            "http": self.proxy_addr,
            "https": None
        })
        self.session = CachedClientSession(proxy=self.proxy_addr, name="cache.bot", trust_env=True)
        self.db = Database(self)
        self.mangadex_api = MangaDexAPI(self.session)
        self.comick_api = ComickAppAPI(self.session)

    async def close(self):
        # await self.cf_scraper.close()
        await self.session.close()
        self.curl_session.close() if self.curl_session else None

    async def __aenter__(self):
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

    @staticmethod
    def load_config() -> Dict:
        config = load_config(logger, auto_exit=False)
        return ensure_configs(logger, config, SCANLATORS, auto_exit=False)


class ExpectedResult:
    def __init__(
            self,
            scanlator_name: str,
            manga_url: str,
            completed: bool,
            human_name: str,
            manga_id: str | int,
            curr_chapter_url: str,
            first_chapter_url: str,
            cover_image: str,
            last_3_chapter_urls: list[str]):
        self.scanlator_name: str = scanlator_name
        self.manga_url: str = manga_url.rstrip("/")
        self.completed: bool = completed
        self.human_name: str = human_name
        self.manga_id: str | int = manga_id
        self.curr_chapter_url: str = curr_chapter_url.rstrip("/")
        self.first_chapter_url: str = first_chapter_url.rstrip("/")
        self.cover_image: str = cover_image.rstrip("/")
        self.last_3_chapter_urls: list[str] = [x.rstrip("/") for x in last_3_chapter_urls]

        if len(self.last_3_chapter_urls) != 3:
            raise ValueError(f"[{scanlator_name}] Expected 3 chapter urls, got {len(self.last_3_chapter_urls)}")

    def extract_last_read_chapter(self, manga: Manga) -> Optional[Chapter]:
        for chapter in manga.available_chapters:
            if chapter.url.rstrip("/") == self.last_3_chapter_urls[0].rstrip("/"):
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
            test_subject: Type[ABCScan],
            id_first: bool = False
    ):
        self.test_subject: Type[ABCScan] = test_subject
        self.test_data: TestInputData = test_data
        self.expected_result: ExpectedResult = expected_result
        self.setup_test = test_setup
        self._bot: Bot = self.setup_test.bot
        self.id_first: bool = id_first

        self.manga_id: str | int | None = None
        self.fmt_url: str | None = None

    async def fmt_manga_url(self) -> bool:
        result = await self.test_subject.fmt_manga_url(self._bot, self.manga_id, self.test_data.manga_url)
        self.fmt_url = result
        evaluated: bool = result == self.expected_result.manga_url
        if not evaluated:
            print(f"Expected: {self.expected_result.manga_url}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def get_manga_id(self) -> bool:
        result = await self.test_subject.get_manga_id(self._bot, self.fmt_url or self.test_data.manga_url)
        self.manga_id = result
        evaluated: bool = result == self.expected_result.manga_id
        if not evaluated:
            print(f"Expected: {self.expected_result.manga_id}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def is_completed(self) -> bool:
        result = await self.test_subject.is_series_completed(self._bot, self.manga_id, self.fmt_url)
        evaluated: bool = result == self.expected_result.completed
        if not evaluated:
            print(f"Expected: {self.expected_result.completed}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def human_name(self) -> bool:
        result = await self.test_subject.get_human_name(self._bot, self.manga_id, self.fmt_url)
        evaluated: bool = result == self.expected_result.human_name
        if not evaluated:
            print(f"Expected: {self.expected_result.human_name}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def curr_chapter_url(self) -> bool:
        result = await self.test_subject.get_curr_chapter(self._bot, self.manga_id, self.fmt_url)
        evaluated = result is not None and result.url.rstrip("/") == self.expected_result.curr_chapter_url.rstrip("/")
        if not evaluated:
            print(f"Expected: {self.expected_result.curr_chapter_url}")
            print(f"   ↳ Got: {result.url}")
        return evaluated

    async def first_chapter_url(self) -> bool:
        result = await self.test_subject.get_all_chapters(self._bot, self.manga_id, self.fmt_url)
        evaluated: bool = (
                result is not None and result[0].url.rstrip("/") == self.expected_result.first_chapter_url.rstrip("/")
        )
        if not evaluated:
            print(f"Expected: {self.expected_result.first_chapter_url}")
            print(f"   ↳ Got: {result[0].url}")
        return evaluated

    async def cover_image(self) -> bool:
        result = await self.test_subject.get_cover_image(self._bot, self.manga_id, self.fmt_url)
        result = result.split("?")[0].rstrip("/")  # remove URL params
        evaluated: bool = result == self.expected_result.cover_image
        if not evaluated:
            print(f"Expected: {self.expected_result.cover_image}")
            print(f"   ↳ Got: {result}")
        return evaluated

    async def check_updates(self) -> bool:
        # As long as the previous tests pass, the make_manga_object method should automatically pass
        manga = await self.test_subject.make_manga_object(self._bot, self.manga_id, self.fmt_url)
        # get the last read chapter where the url == last_3_chapter_urls[0]
        last_read_chapter = self.expected_result.extract_last_read_chapter(manga)
        if not last_read_chapter:
            print(f"Expected: {self.expected_result.last_3_chapter_urls[0]}")
            print(f"   ↳ Got: {manga.available_chapters[-3].url if len(manga.available_chapters) >= 3 else None}")
            raise AssertionError("❌ Last 3 chapter urls at index 0 does not match any chapter in the manga object")
        manga._last_chapter = last_read_chapter
        result = await self.test_subject.check_updates(self._bot, manga)
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

    def scanlator_name(self) -> bool:
        evaluated: bool = self.test_subject.name == self.expected_result.scanlator_name
        if not evaluated:
            print(f"Expected: {self.expected_result.scanlator_name}")
            print(f"   ↳ Got: {self.test_subject.name}")
        return evaluated

    async def begin(self) -> str:
        checks_passed: int = 0
        print(f"🔎 [{self.expected_result.scanlator_name}] Running tests...")
        checks_to_run: list[tuple[callable, str]] = [
            (self.get_manga_id, "❌ Failed to get manga id"),
            (self.fmt_manga_url, "❌ Failed to format manga url"),
            (self.is_completed, "❌ Failed to get completed status"),
            (self.human_name, "❌ Failed to get human name"),
            (self.curr_chapter_url, "❌ Failed to get current chapter url"),
            (self.first_chapter_url, "❌ Failed to get first chapter url"),
            (self.cover_image, "❌ Failed to get cover image"),
            (self.check_updates, "❌ Failed to check for updates"),
            (self.scanlator_name, "❌ Failed to match scanlator name to expected name")
        ]
        if not self.id_first:
            checks_to_run[0], checks_to_run[1] = checks_to_run[1], checks_to_run[0]

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
    test_subject: Type[ABCScan]
    test: Test | None = None
    id_first: bool = False

    def setup(self):
        self.test = Test(self.test_setup, self.test_data, self.expected_result, self.test_subject, self.id_first)

    async def begin(self) -> str:
        if self.test_subject.name not in SCANLATORS:
            print(f"Scanlator {self.test_subject} is disabled! No tests will be run.")
            return "N/A"
        else:
            return await self.test.begin()


def default_id_func(manga_url: str) -> str:
    return hashlib.sha256(manga_url.encode()).hexdigest()


def toggle_logging(name: str = "__main__") -> logging.Logger:
    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(logging.StreamHandler())
    return _logger


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


async def run_single_test(test_case: TestCase):
    test_case.setup()
    await test_case.begin()


if __name__ == "__main__":
    # noinspection SpellCheckingInspection
    async def main():
        test_setup = SetupTest()

        testCases = {
            "tritinia": TestCase(
                test_setup,
                test_data=TestInputData("https://tritinia.org/manga/momo-the-blood-taker/"),
                expected_result=ExpectedResult(
                    scanlator_name="tritinia",
                    manga_url="https://tritinia.org/manga/momo-the-blood-taker/",
                    completed=True,
                    human_name="MOMO: The Blood Taker",
                    manga_id=default_id_func("https://tritinia.org/manga/momo-the-blood-taker"),
                    curr_chapter_url="https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-48/",
                    first_chapter_url=(
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-1/ch-1-v-coming-soon-scans/"
                    ),
                    cover_image="https://tritinia.org/wp-content/uploads/2022/02/000-193x278.jpg",
                    last_3_chapter_urls=[
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-46/",
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-47/",
                        "https://tritinia.org/manga/momo-the-blood-taker/volume-5/ch-48/",
                    ]
                ),
                test_subject=TritiniaScans
            ),
            "manganato": TestCase(
                test_setup,
                test_data=TestInputData("https://chapmanganato.com/manga-hf985162"),
                expected_result=ExpectedResult(
                    scanlator_name="manganato",
                    manga_url="https://chapmanganato.com/manga-hf985162",
                    completed=False,
                    human_name="God Of Blackfield",
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
                test_subject=Manganato,
                id_first=True
            ),
            "toonily": TestCase(
                test_setup,
                test_data=TestInputData(
                    "https://toonily.com/webtoon/lucky-guy-0002/"
                ),
                expected_result=ExpectedResult(
                    scanlator_name="toonily",
                    manga_url="https://toonily.com/webtoon/lucky-guy-0002/",
                    completed=True,
                    human_name="Lucky Guy",
                    manga_id=default_id_func("https://toonily.com/webtoon/lucky-guy-0002"),
                    curr_chapter_url="https://toonily.com/webtoon/lucky-guy-0002/chapter-73/",
                    first_chapter_url="https://toonily.com/webtoon/lucky-guy-0002/chapter-1/",
                    cover_image=(
                        "https://toonily.com/wp-content/uploads/2020/02/Lucky-Guy-224x320.jpg"),
                    last_3_chapter_urls=[
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-71/",
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-72/",
                        "https://toonily.com/webtoon/lucky-guy-0002/chapter-73/",
                    ]
                ),
                test_subject=Toonily
            ),
            "mangadex": TestCase(
                test_setup,
                test_data=TestInputData("https://mangadex.org/title/7dbeaa0e-420a-4dc0-b2d3-eb174de266da/zippy-ziggy"),
                expected_result=ExpectedResult(
                    scanlator_name="mangadex",
                    manga_url="https://mangadex.org/title/7dbeaa0e-420a-4dc0-b2d3-eb174de266da",
                    completed=True,
                    human_name="Zippy Ziggy",
                    manga_id="7dbeaa0e-420a-4dc0-b2d3-eb174de266da",
                    curr_chapter_url="https://mangadex.org/chapter/aef242d7-0051-431f-9f03-53442afdbead",
                    first_chapter_url="https://mangadex.org/chapter/388124f0-dc2e-43db-b19e-71d0e3eddfc6",
                    cover_image=(
                        "https://uploads.mangadex.org/covers/7dbeaa0e-420a-4dc0-b2d3-eb174de266da/192e6a85-80d5-42b4"
                        "-bdda-81b56592c44f.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://mangadex.org/chapter/03402aaa-8eba-43ac-a83e-ce336c75aa62",
                        "https://mangadex.org/chapter/ee43a7c7-595a-4006-9dc0-df44b0f37b59",
                        "https://mangadex.org/chapter/aef242d7-0051-431f-9f03-53442afdbead",
                    ]
                ),
                test_subject=MangaDex,
            ),
            "flamescans": TestCase(
                test_setup,
                test_data=TestInputData("https://flamescans.org/series/1687428121-the-villainess-is-a-marionette/"),
                expected_result=ExpectedResult(
                    scanlator_name="flamescans",
                    manga_url="https://flamescans.org/series/the-villainess-is-a-marionette/",
                    completed=True,
                    human_name="The Villainess is a Marionette",
                    manga_id=default_id_func("https://flamescans.org/series/the-villainess-is-a-marionette"),
                    curr_chapter_url="https://flamescans.org/the-villainess-is-a-marionette-chapter-69/",
                    first_chapter_url="https://flamescans.org/the-villainess-is-a-marionette-chapter-0/",
                    cover_image="https://flamescans.org/wp-content/uploads/2021/02/VIAM_S2_COVER.jpg",
                    last_3_chapter_urls=[
                        "https://flamescans.org/the-villainess-is-a-marionette-chapter-67/",
                        "https://flamescans.org/the-villainess-is-a-marionette-chapter-68/",
                        "https://flamescans.org/the-villainess-is-a-marionette-chapter-69/",
                    ]
                ),
                test_subject=FlameScans
            ),
            "asurascans": TestCase(
                test_setup,
                test_data=TestInputData("https://www.asurascans.com/manga/4569947261-i-regressed-as-the-duke/"),
                expected_result=ExpectedResult(
                    scanlator_name="asurascans",
                    manga_url="https://www.asurascans.com/manga/i-regressed-as-the-duke/",
                    completed=True,
                    human_name="I Regressed As The Duke",
                    manga_id=default_id_func(
                        "https://www.asurascans.com/manga/i-regressed-as-the-duke"
                    ),
                    curr_chapter_url="https://www.asurascans.com/i-regressed-as-the-duke-chapter-64-notice/",
                    first_chapter_url="https://www.asurascans.com/i-regressed-as-the-duke-chapter-1/",
                    cover_image="https://www.asurascans.com/wp-content/uploads/2022/04/unknown_1-1.png",
                    last_3_chapter_urls=[
                        "https://www.asurascans.com/i-regressed-as-the-duke-chapter-62/",
                        "https://www.asurascans.com/i-regressed-as-the-duke-chapter-63/",
                        "https://www.asurascans.com/i-regressed-as-the-duke-chapter-64-notice/",
                    ]
                ),
                test_subject=AsuraScans
            ),
            "aquamanga": TestCase(
                test_setup,
                test_data=TestInputData("https://aquamanga.com/read/court-swordswoman-in-another-world/"),
                expected_result=ExpectedResult(
                    scanlator_name="aquamanga",
                    manga_url="https://aquamanga.com/read/court-swordswoman-in-another-world/",
                    completed=True,
                    human_name="Court Swordswoman in Another World",
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
                test_subject=Aquamanga
            ),
            "reaperscans": TestCase(
                test_setup,
                test_data=TestInputData("https://reaperscans.com/comics/4099-the-legendary-mechanic"),
                expected_result=ExpectedResult(
                    scanlator_name="reaperscans",
                    manga_url="https://reaperscans.com/comics/4099-the-legendary-mechanic",
                    completed=True,
                    human_name="The Legendary Mechanic",
                    manga_id="4099",
                    curr_chapter_url=(
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/22619310-chapter-10"
                    ),
                    first_chapter_url=(
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/24239107-chapter-0"
                    ),
                    cover_image=(
                        "https://media.reaperscans.com/file/4SRBHm/comics/167d3d48-6d3a-4af3-9e04-183c28938df8"
                        "/NnJgo5uCLKDisl2OSBtbBKDbZYdqUeeeGjH8qoh2.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/56469949-chapter-8",
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/11904616-chapter-9",
                        "https://reaperscans.com/comics/4099-the-legendary-mechanic/chapters/22619310-chapter-10",
                    ],
                ),
                id_first=True,
                test_subject=ReaperScans,
            ),
            "aniglisscans": TestCase(
                test_setup,
                test_data=TestInputData("https://anigliscans.com/series/blooming/"),
                expected_result=ExpectedResult(
                    scanlator_name="aniglisscans",
                    manga_url="https://anigliscans.com/series/blooming/",
                    completed=True,
                    human_name="BLOOMING",
                    manga_id=default_id_func("https://anigliscans.com/series/blooming"),
                    curr_chapter_url="https://anigliscans.com/blooming-chapter-24/",
                    first_chapter_url="https://anigliscans.com/blooming-chapter-1/",
                    cover_image="https://anigliscans.com/wp-content/uploads/2022/07/blooming_cov.png",
                    last_3_chapter_urls=[
                        "https://anigliscans.com/blooming-chapter-22/",
                        "https://anigliscans.com/blooming-chapter-23/",
                        "https://anigliscans.com/blooming-chapter-24/",
                    ],
                ),
                test_subject=AniglisScans
            ),
            "comick": TestCase(
                test_setup,
                test_data=TestInputData("https://comick.app/comic/00-solo-leveling?lang=en"),
                expected_result=ExpectedResult(
                    scanlator_name="comick",
                    manga_url="https://comick.app/comic/00-solo-leveling?lang=en",
                    completed=True,
                    human_name="Solo Leveling",
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
                test_subject=Comick
            ),
            "voidscans": TestCase(
                test_setup,
                test_data=TestInputData("https://void-scans.com/manga/superhuman-era/"),
                expected_result=ExpectedResult(
                    scanlator_name="voidscans",
                    manga_url="https://void-scans.com/manga/superhuman-era/",
                    completed=False,
                    human_name="Superhuman Era",
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
                test_subject=VoidScans
            ),
            "luminousscans": TestCase(
                test_setup,
                test_data=TestInputData("https://luminousscans.com/series/1680246102-my-office-noonas-story/"),
                expected_result=ExpectedResult(
                    scanlator_name="luminousscans",
                    manga_url="https://luminousscans.com/series/1680246102-my-office-noonas-story/",
                    completed=True,
                    human_name="My Office Noona’s Story",
                    manga_id="1680246102",
                    curr_chapter_url="https://luminousscans.com/1680246102-my-office-noonas-story-epilogue-chapter-03/",
                    first_chapter_url="https://luminousscans.com/1680246102-my-office-noonas-story-prologue/",
                    cover_image="https://luminousscans.com/wp-content/uploads/2021/05/My_Office_Noona_Story_Title-1.jpg",
                    last_3_chapter_urls=[
                        "https://luminousscans.com/1680246102-my-office-noonas-story-epilogue-chapter-01/",
                        "https://luminousscans.com/1680246102-my-office-noonas-story-epilogue-chapter-02/",
                        "https://luminousscans.com/1680246102-my-office-noonas-story-epilogue-chapter-03/",
                    ],
                ),
                id_first=True,
                test_subject=LuminousScans
            ),
            "leviatanscans": TestCase(
                test_setup,
                test_data=TestInputData("https://en.leviatanscans.com/manga/trash-of-the-counts-family/"),
                expected_result=ExpectedResult(
                    scanlator_name="leviatanscans",
                    manga_url="https://en.leviatanscans.com/manga/trash-of-the-counts-family/",
                    completed=False,
                    human_name="Trash of the Count’s Family",
                    manga_id=default_id_func("https://en.leviatanscans.com/manga/trash-of-the-counts-family"),
                    curr_chapter_url="https://en.leviatanscans.com/manga/trash-of-the-counts-family/chapter-92/",
                    first_chapter_url="https://en.leviatanscans.com/manga/trash-of-the-counts-family/chapter-0/",
                    cover_image="https://en.leviatanscans.com/wp-content/uploads/2023/04/bannerTCF.jpg",
                    last_3_chapter_urls=[
                        "https://en.leviatanscans.com/manga/trash-of-the-counts-family/chapter-90/",
                        "https://en.leviatanscans.com/manga/trash-of-the-counts-family/chapter-91/",
                        "https://en.leviatanscans.com/manga/trash-of-the-counts-family/chapter-92/",
                    ],
                ),
                test_subject=LeviatanScans
            ),
            "drakescans": TestCase(
                test_setup,
                test_data=TestInputData("https://drakescans.com/series/spirit-pet-creation-simulator1/"),
                expected_result=ExpectedResult(
                    scanlator_name="drakescans",
                    manga_url="https://drakescans.com/series/spirit-pet-creation-simulator1/",
                    completed=True,
                    human_name="Spirit Pet Creation Simulator",
                    manga_id=default_id_func("https://drakescans.com/series/spirit-pet-creation-simulator1"),
                    curr_chapter_url="https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-28/",
                    first_chapter_url="https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-00/",
                    cover_image="https://drakescans.com/wp-content/uploads/2022/02/01-193x278.jpg",
                    last_3_chapter_urls=[
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-26/",
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-27/",
                        "https://drakescans.com/series/spirit-pet-creation-simulator1/chapter-28/",
                    ],
                ),
                test_subject=DrakeScans
            ),
            "nitroscans": TestCase(
                test_setup,
                test_data=TestInputData("https://nitroscans.com/mangas/spirit-pet-creation-simulator/"),
                expected_result=ExpectedResult(
                    scanlator_name="nitroscans",
                    manga_url="https://nitroscans.com/mangas/spirit-pet-creation-simulator/",
                    completed=True,
                    human_name="Spirit Pet Creation Simulator",
                    manga_id=default_id_func("https://nitroscans.com/mangas/spirit-pet-creation-simulator"),
                    curr_chapter_url="https://nitroscans.com/mangas/spirit-pet-creation-simulator/chapter-28/",
                    first_chapter_url="https://nitroscans.com/mangas/spirit-pet-creation-simulator/chapter-0/",
                    cover_image=(
                        "https://nitroscans.com/wp-content/uploads/2022/05/Spirit-Pet-Creation-Simulator-193x278.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://nitroscans.com/mangas/spirit-pet-creation-simulator/chapter-26/",
                        "https://nitroscans.com/mangas/spirit-pet-creation-simulator/chapter-27/",
                        "https://nitroscans.com/mangas/spirit-pet-creation-simulator/chapter-28/",
                    ],
                ),
                test_subject=NitroScans
            ),
            "mangapill": TestCase(
                test_setup,
                test_data=TestInputData("https://mangapill.com/manga/57/3d-kanojo"),
                expected_result=ExpectedResult(
                    scanlator_name="mangapill",
                    manga_url="https://mangapill.com/manga/57/3d-kanojo",
                    completed=True,
                    human_name="3D Kanojo",
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
                test_subject=Mangapill
            ),
            "bato.to": TestCase(
                test_setup,
                test_data=TestInputData("https://bato.to/series/95400/queen-in-the-shadows"),
                expected_result=ExpectedResult(
                    scanlator_name="bato.to",
                    manga_url="https://bato.to/series/95400/queen-in-the-shadows",
                    completed=True,
                    human_name="Queen in the Shadows",
                    manga_id="95400",
                    curr_chapter_url="https://bato.to/chapter/2031007",
                    first_chapter_url="https://bato.to/chapter/1803219",
                    cover_image=(
                        "https://xfs-s118.batcg.org/thumb/W600/ampi/515"
                        "/5153a1fcfcfd904decc8777384a7e5511c195a09_400_600_65091.jpeg"
                    ),
                    last_3_chapter_urls=[
                        "https://bato.to/chapter/2018714",
                        "https://bato.to/chapter/2029629",
                        "https://bato.to/chapter/2031007",
                    ],
                ),
                id_first=True,
                test_subject=Bato
            ),
            "omegascans": TestCase(
                test_setup,
                test_data=TestInputData("https://omegascans.org/series/dorm-room-sisters"),
                expected_result=ExpectedResult(
                    scanlator_name="omegascans",
                    manga_url="https://omegascans.org/series/dorm-room-sisters",
                    completed=True,
                    human_name="Dorm Room Sisters",
                    manga_id=default_id_func("https://omegascans.org/series/dorm-room-sisters"),
                    curr_chapter_url="https://omegascans.org/series/dorm-room-sisters/chapter-93-5-review",
                    first_chapter_url="https://omegascans.org/series/dorm-room-sisters/chapter-1",
                    cover_image=(
                        "https://media.omegascans.org/file/zFSsXt/covers/12333c4d-d82c-4a88-8b55-7f5e5f266457.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://omegascans.org/series/dorm-room-sisters/chapter-92",
                        "https://omegascans.org/series/dorm-room-sisters/chapter-93-end",
                        "https://omegascans.org/series/dorm-room-sisters/chapter-93-5-review",
                    ],
                ),
                test_subject=OmegaScans,
            )
        }

        if os.name == "nt":
            os.name = "posix"  # debug on posix systems (linux, macos, etc)
            logger.warning("asurascans, reaperscans and voidscans cannot be tested on windows.")
            logger.warning("Use WSL instead.")
            testCases.pop("asurascans", None)
            testCases.pop("reaperscans", None)
            testCases.pop("voidscans", None)

        if (user := os.environ.get("HOME")) is not None:
            if user.split("/")[-1] == "mooshi":
                ...
            else:
                testCases.pop("voidscans", None)  # remove voidscans from testinc in GitHub Actions

        # toggle_logging("cache.curl_cffi")
        # toggle_logging("cache.bot")
        
        try:
            tests_to_ignore = ["nitroscans"]  # going through changes on website, gotta wait till done
            await run_tests(testCases, tests_to_ignore)
            # await run_single_test(testCases["asurascans"])
        finally:
            await test_setup.bot.close()


    import asyncio

    asyncio.run(main())
