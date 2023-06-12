"""
This is a test file for testing each individual scanlator class from scanlator.py

# Path: test.py
"""
from __future__ import annotations

from typing import Dict, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    # from src.core import MangaClient
    ...

import hashlib

from dataclasses import dataclass

from src.core.scanners import *
from src.core.database import Database
from src.core.comickAPI import ComickAppAPI
from src.core.mangadexAPI import MangaDexAPI
from src.core.cache import CachedClientSession
from src.core.cf_bypass import ProtectedRequest

from src.core.objects import Chapter, Manga


# noinspection PyTypeChecker
class Bot:
    def __init__(self, proxy_url: Optional[str] = None):
        self.config: Dict = None
        self.cf_scraper = ProtectedRequest(self)
        self.session = CachedClientSession(proxy=proxy_url)
        self.db = Database(self)
        self.mangadex_api = MangaDexAPI(self.session)
        self.comick_api = ComickAppAPI(self.session)

    async def close(self):
        await self.cf_scraper.close()
        await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class SetupTest:
    proxy_url: str = None
    bot: Bot = None

    def setup(self):
        self.bot = Bot(proxy_url=self.proxy_url)
        self.bot.config = self.load_config()
        self.proxy_url = self.fmt_proxy()
        return self

    @staticmethod
    def load_config() -> Dict:
        import yaml
        with open("config.yml", "r") as f:
            config = yaml.safe_load(f)
        return config

    def fmt_proxy(self) -> str:
        proxy_dict = self.bot.config["proxy"]
        return f"http://{proxy_dict['username']}:{proxy_dict['password']}@{proxy_dict['ip']}:{proxy_dict['port']}"


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
        self.last_3_chapter_urls: list[str] = list(sorted([x.rstrip("/") for x in last_3_chapter_urls]))

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
    def __init__(self, test_data: TestInputData, expected_result: ExpectedResult, test_subject: Type[ABCScan],
                 id_first: bool = False):
        self.test_subject: Type[ABCScan] = test_subject
        self.test_data: TestInputData = test_data
        self.expected_result: ExpectedResult = expected_result
        self.setup_test = SetupTest().setup()
        self._bot: Bot = self.setup_test.bot
        self.id_first: bool = id_first

        self.manga_id: str | int | None = None
        self.fmt_url: str | None = None

    async def fmt_manga_url(self) -> bool:
        result = await self.test_subject.fmt_manga_url(self._bot, self.manga_id or None, self.test_data.manga_url)
        self.fmt_url = result
        return result == self.expected_result.manga_url

    async def get_manga_id(self) -> bool:
        result = await self.test_subject.get_manga_id(self._bot, self.fmt_url or self.test_data.manga_url)
        self.manga_id = result
        return result == self.expected_result.manga_id

    async def is_completed(self) -> bool:
        result = await self.test_subject.is_series_completed(self._bot, self.manga_id, self.fmt_url)
        return result == self.expected_result.completed

    async def human_name(self) -> bool:
        result = await self.test_subject.get_human_name(self._bot, self.manga_id, self.fmt_url)
        return result == self.expected_result.human_name

    async def curr_chapter_url(self) -> bool:
        result = await self.test_subject.get_curr_chapter(self._bot, self.manga_id, self.fmt_url)
        return result is not None and result.url.rstrip("/") == self.expected_result.curr_chapter_url.rstrip("/")

    async def first_chapter_url(self) -> bool:
        result = await self.test_subject.get_all_chapters(self._bot, self.manga_id, self.fmt_url)
        return result is not None and result[0].url.rstrip("/") == self.expected_result.first_chapter_url.rstrip("/")

    async def cover_image(self) -> bool:
        result = await self.test_subject.get_cover_image(self._bot, self.manga_id, self.fmt_url)
        return result == self.expected_result.cover_image

    async def check_updates(self) -> bool:
        # As long as the previous tests pass, the make_manga_object method should automatically pass
        manga = await self.test_subject.make_manga_object(self._bot, self.manga_id, self.fmt_url)
        # get the last read chapter where the url == last_3_chapter_urls[0]
        last_read_chapter = self.expected_result.extract_last_read_chapter(manga)
        if not last_read_chapter:
            raise AssertionError("❌ Last 3 chapter urls at index 0 does not match any chapter in the manga object")
        manga._last_chapter = last_read_chapter
        result = await self.test_subject.check_updates(self._bot, manga)
        return all(
            [
                result.new_chapters[i].url.rstrip("/") == (self.expected_result.last_3_chapter_urls[-2:][i].rstrip("/"))
                for i in range(2)
            ]
        )

    def scanlator_name(self) -> bool:
        return self.test_subject.name == self.expected_result.scanlator_name

    async def begin(self) -> bool:
        print(f"🔎 [{self.expected_result.scanlator_name}] Running tests...")
        try:
            if self.id_first:
                assert await self.get_manga_id(), "❌ Failed to get manga id"
                assert await self.fmt_manga_url(), "❌ Failed to format manga url"
            else:
                assert await self.fmt_manga_url(), "❌ Failed to format manga url"
                assert await self.get_manga_id(), "❌ Failed to get manga id"

            assert await self.is_completed(), "❌ Failed to get completed status"
            assert await self.human_name(), "❌ Failed to get human name"
            assert await self.curr_chapter_url(), "❌ Failed to get current chapter url"
            assert await self.first_chapter_url(), "❌ Failed to get first chapter url"
            assert await self.cover_image(), "❌ Failed to get cover image"
            assert await self.check_updates(), "❌ Failed to check updates"
            assert self.scanlator_name(), "❌ Failed matching scanlator name to expected result"
            print(f"✅ [{self.expected_result.scanlator_name}] All tests passed!")
            return True
        except AssertionError as e:
            print(e)
            return False
        finally:
            await self._bot.close()


@dataclass
class TestCase:
    test_data: TestInputData
    expected_result: ExpectedResult
    test_subject: Type[ABCScan]
    test: Test | None = None
    id_first: bool = False

    def setup(self):
        self.test = Test(self.test_data, self.expected_result, self.test_subject, self.id_first)

    async def begin(self):
        await self.test.begin()


def default_id_func(manga_url: str) -> str:
    return hashlib.sha256(manga_url.encode()).hexdigest()


async def run_tests(test_cases: list[TestCase]):
    for test_case in test_cases:
        test_case.setup()
        await test_case.begin()


if __name__ == "__main__":
    testCases = [
        TestCase(
            test_data=TestInputData("https://tritinia.org/manga/useless-magician/"),
            expected_result=ExpectedResult(
                scanlator_name="tritinia",
                manga_url="https://tritinia.org/manga/useless-magician/",
                completed=False,
                human_name="Useless Wizard",
                manga_id=default_id_func("https://tritinia.org/manga/useless-magician"),
                curr_chapter_url="https://tritinia.org/manga/useless-magician/ch-24/",
                first_chapter_url="https://tritinia.org/manga/useless-magician/ch-1/",
                cover_image="https://tritinia.org/wp-content/uploads/2022/10/cover_x2-193x278.jpg",
                last_3_chapter_urls=[
                    "https://tritinia.org/manga/useless-magician/ch-24/",
                    "https://tritinia.org/manga/useless-magician/ch-23/",
                    "https://tritinia.org/manga/useless-magician/ch-22/"
                ]
            ),
            test_subject=TritiniaScans
        ),
        TestCase(
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
                    "https://chapmanganato.com/manga-hf985162/chapter-155",
                    "https://chapmanganato.com/manga-hf985162/chapter-154",
                    "https://chapmanganato.com/manga-hf985162/chapter-153"
                ]
            ),
            test_subject=Manganato,
            id_first=True
        ),
        TestCase(
            test_data=TestInputData(
                "https://toonily.com/webtoon/please-give-me-energy/"
            ),
            expected_result=ExpectedResult(
                scanlator_name="toonily",
                manga_url="https://toonily.com/webtoon/please-give-me-energy/",
                completed=False,
                human_name="Please Give Me Energy",
                manga_id=default_id_func(
                    "https://toonily.com/webtoon/please-give-me-energy"
                ),
                curr_chapter_url="https://toonily.com/webtoon/please-give-me-energy/chapter-40/",
                first_chapter_url="https://toonily.com/webtoon/please-give-me-energy/chapter-1/",
                cover_image=("https://toonily.com/wp-content/uploads/2022/10/Please-Give-Me-Energy-toptoon-manhwa-free"
                             "-224x320.jpg"),
                last_3_chapter_urls=[
                    "https://toonily.com/webtoon/please-give-me-energy/chapter-40/",
                    "https://toonily.com/webtoon/please-give-me-energy/chapter-39/",
                    "https://toonily.com/webtoon/please-give-me-energy/chapter-38/"
                ]
            ),
            test_subject=Toonily
        ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=MangaDex,
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=FlameScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=AsuraScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=Aquamanga
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=ReaperScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=AniglisScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=Comick
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=VoidScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=LuminousScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=LeviatanScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=DrakeScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=NitroScans
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=Mangapill
        # ),
        # TestCase(
        #     test_data=TestInputData(),
        #     expected_result=ExpectedResult(),
        #     test_subject=Bato
        # )
    ]

    import asyncio

    asyncio.run(run_tests(testCases))
