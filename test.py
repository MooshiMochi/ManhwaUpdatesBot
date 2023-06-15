"""
This is a test file for testing each individual scanlator class from scanlator.py

# Path: test.py
"""
from __future__ import annotations

import hashlib
import os
from asyncio import iscoroutinefunction
from dataclasses import dataclass
from typing import Dict, Optional, Type

from src.core.cache import CachedClientSession
from src.core.cf_bypass import ProtectedRequest
from src.core.comickAPI import ComickAppAPI
from src.core.database import Database
from src.core.mangadexAPI import MangaDexAPI
from src.core.scanners import *


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

    @staticmethod
    async def log_to_discord(message, **kwargs):
        print(message, kwargs)


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
        if os.name == "nt":
            print("Running on Windows, using config.yml")
            import yaml
            with open("config.yml", "r") as f:
                config = yaml.safe_load(f)
            return config
        else:
            return {}

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
        result = await self.test_subject.fmt_manga_url(self._bot, self.manga_id or None, self.test_data.manga_url)
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
        return await self.test.begin()


def default_id_func(manga_url: str) -> str:
    return hashlib.sha256(manga_url.encode()).hexdigest()


async def run_tests(test_cases: list[TestCase]):
    successful_tests = 0
    for test_case in test_cases:
        test_case.setup()
        checks_passed: str = await test_case.begin()
        passed_of_total = checks_passed.split("/")
        if passed_of_total[0] == passed_of_total[1]:
            successful_tests += 1

    total_tests = len(test_cases)
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
        test_setup = SetupTest().setup()

        testCases = [
            TestCase(
                test_setup,
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
                        "https://tritinia.org/manga/useless-magician/ch-22/",
                        "https://tritinia.org/manga/useless-magician/ch-23/",
                        "https://tritinia.org/manga/useless-magician/ch-24/",
                    ]
                ),
                test_subject=TritiniaScans
            ),
            TestCase(
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
            TestCase(
                test_setup,
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
                    cover_image=(
                        "https://toonily.com/wp-content/uploads/2022/10/Please-Give-Me-Energy-toptoon-manhwa-free"
                        "-224x320.jpg"),
                    last_3_chapter_urls=[
                        "https://toonily.com/webtoon/please-give-me-energy/chapter-38/",
                        "https://toonily.com/webtoon/please-give-me-energy/chapter-39/",
                        "https://toonily.com/webtoon/please-give-me-energy/chapter-40/",
                    ]
                ),
                test_subject=Toonily
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://mangadex.org/title/8b34f37a-0181-4f0b-8ce3-01217e9a602c"),
                expected_result=ExpectedResult(
                    scanlator_name="mangadex",
                    manga_url="https://mangadex.org/title/8b34f37a-0181-4f0b-8ce3-01217e9a602c",
                    completed=False,
                    human_name="Please Bully Me, Miss Villainess!",
                    manga_id="8b34f37a-0181-4f0b-8ce3-01217e9a602c",
                    curr_chapter_url="https://mangadex.org/chapter/42cefe93-2113-4ae9-bab6-5a97169a1343",
                    first_chapter_url="https://mangadex.org/chapter/988a7365-e411-4fe1-b705-ea16dcda21de",
                    cover_image=(
                        "https://uploads.mangadex.org/covers/8b34f37a-0181-4f0b-8ce3-01217e9a602c/71e4f7c8-3fb3-4c10-bb07"
                        "-63b3f82c370e.jpg"
                    ),
                    last_3_chapter_urls=[
                        "https://mangadex.org/chapter/98a201b4-c07d-4911-a4c6-b864df66a617",
                        "https://mangadex.org/chapter/b241cfd8-46f3-49a2-ab7c-0ce50c041320",
                        "https://mangadex.org/chapter/42cefe93-2113-4ae9-bab6-5a97169a1343",
                    ]
                ),
                test_subject=MangaDex,
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://flamescans.org/series/1686650521-solo-necromancy/"),
                expected_result=ExpectedResult(
                    scanlator_name="flamescans",
                    manga_url="https://flamescans.org/series/solo-necromancy/",
                    completed=False,
                    human_name="Solo Necromancy",
                    manga_id=default_id_func("https://flamescans.org/series/solo-necromancy"),
                    curr_chapter_url="https://flamescans.org/solo-necromancy-chapter-95/",
                    first_chapter_url="https://flamescans.org/solo-necromancy-chapter-1/",
                    cover_image="https://flamescans.org/wp-content/uploads/2021/09/3.3MB-SN-Updated-2-WEBP-1.webp",
                    last_3_chapter_urls=[
                        "https://flamescans.org/solo-necromancy-chapter-91/",
                        "https://flamescans.org/solo-necromancy-chapter-92/",
                        "https://flamescans.org/solo-necromancy-chapter-93/",
                    ]
                ),
                test_subject=FlameScans
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://www.asurascans.com/manga/the-knight-king-who-returned-with-a-god/"),
                expected_result=ExpectedResult(
                    scanlator_name="asurascans",
                    manga_url="https://www.asurascans.com/manga/the-knight-king-who-returned-with-a-god/",
                    completed=False,
                    human_name="The Knight King Who Returned with a God",
                    manga_id=default_id_func(
                        "https://www.asurascans.com/manga/the-knight-king-who-returned-with-a-god"
                    ),
                    curr_chapter_url="https://www.asurascans.com/the-knight-king-who-returned-with-a-god-chapter-8/",
                    first_chapter_url="https://www.asurascans.com/the-knight-king-who-returned-with-a-god-chapter-1/",
                    cover_image="https://www.asurascans.com/wp-content/uploads/2023/05/theknightkingCover01.png",
                    last_3_chapter_urls=[
                        "https://www.asurascans.com/the-knight-king-who-returned-with-a-god-chapter-6/",
                        "https://www.asurascans.com/the-knight-king-who-returned-with-a-god-chapter-7/",
                        "https://www.asurascans.com/the-knight-king-who-returned-with-a-god-chapter-8/",
                    ]
                ),
                test_subject=AsuraScans
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://aquamanga.com/read/the-world-after-the-fall/"),
                expected_result=ExpectedResult(
                    scanlator_name="aquamanga",
                    manga_url="https://aquamanga.com/read/the-world-after-the-fall/",
                    completed=False,
                    human_name="The World After the Fall",
                    manga_id=default_id_func("https://aquamanga.com/read/the-world-after-the-fall"),
                    curr_chapter_url="https://aquamanga.com/read/the-world-after-the-fall/chapter-78/",
                    first_chapter_url="https://aquamanga.com/read/the-world-after-the-fall/chapter-0/",
                    cover_image="https://aquamanga.com/wp-content/uploads/2022/02/the-world-after-the-fall-193x278.jpeg",
                    last_3_chapter_urls=[
                        "https://aquamanga.com/read/the-world-after-the-fall/chapter-76/",
                        "https://aquamanga.com/read/the-world-after-the-fall/chapter-77/",
                        "https://aquamanga.com/read/the-world-after-the-fall/chapter-78/",
                    ]
                ),
                test_subject=Aquamanga
            ),
            # TestCase(
            #     test_setup,
            #     test_data=TestInputData("https://reaperscans.com/comics/2818-knight-of-the-frozen-flower"),
            #     expected_result=ExpectedResult(
            #         scanlator_name="reaperscans",
            #         manga_url="https://reaperscans.com/comics/2818-knight-of-the-frozen-flower",
            #         completed=False,
            #         human_name="Knight of the Frozen Flower",
            #         manga_id="2818",
            #         curr_chapter_url=(
            #             "https://reaperscans.com/comics/2818-knight-of-the-frozen-flower/chapters/56567166-chapter-59"
            #         ),
            #         first_chapter_url=(
            #             "https://reaperscans.com/comics/2818-knight-of-the-frozen-flower/chapters/18980856-chapter-28"
            #         ),
            #         cover_image=(
            #             "https://media.reaperscans.com/file/4SRBHm/comics/65ea299e-cde7-44c1-b12a-816667d0a205"
            #             "/jhQQJXway6OVyS5B87bq5S6rG8Aak3V5IBtgCFTk.jpg"
            #         ),
            #         last_3_chapter_urls=[
            #             "https://reaperscans.com/comics/2818-knight-of-the-frozen-flower/chapters/56567164-chapter-57",
            #             "https://reaperscans.com/comics/2818-knight-of-the-frozen-flower/chapters/56567165-chapter-58",
            #             "https://reaperscans.com/comics/2818-knight-of-the-frozen-flower/chapters/56567166-chapter-59",
            #         ],
            #     ),
            #     id_first=True,
            #     test_subject=ReaperScans,
            # ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://anigliscans.com/series/doomsday-summoning-frenzy/"),
                expected_result=ExpectedResult(
                    scanlator_name="aniglisscans",
                    manga_url="https://anigliscans.com/series/doomsday-summoning-frenzy/",
                    completed=False,
                    human_name="Doomsday Summoning Frenzy",
                    manga_id=default_id_func("https://anigliscans.com/series/doomsday-summoning-frenzy"),
                    curr_chapter_url="https://anigliscans.com/doomsday-summoning-frenzy-chapter-15/",
                    first_chapter_url="https://anigliscans.com/doomsday-summoning-frenzy-chapter-5/",
                    cover_image="https://anigliscans.com/wp-content/uploads/2023/04/1-1.jpg",
                    last_3_chapter_urls=[
                        "https://anigliscans.com/doomsday-summoning-frenzy-chapter-13/",
                        "https://anigliscans.com/doomsday-summoning-frenzy-chapter-14/",
                        "https://anigliscans.com/doomsday-summoning-frenzy-chapter-15/",
                    ],
                ),
                test_subject=AniglisScans
            ),
            TestCase(
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
            # TestCase(
            #     test_setup,
            #     test_data=TestInputData(),
            #     expected_result=ExpectedResult(),
            #     test_subject=VoidScans
            # ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://luminousscans.com/series/1680246102-legend-of-the-northern-blade/"),
                expected_result=ExpectedResult(
                    scanlator_name="luminousscans",
                    manga_url="https://luminousscans.com/series/1680246102-legend-of-the-northern-blade/",
                    completed=False,
                    human_name="Legend of the Northern Blade",
                    manga_id="1680246102",
                    curr_chapter_url="https://luminousscans.com/legend-of-the-northern-blade-chapter-160/",
                    first_chapter_url="https://luminousscans.com/1680246102-legend-of-the-northern-blade-chapter-92/",
                    cover_image="https://luminousscans.com/wp-content/uploads/2021/07/LONBAnimGif1.gif",
                    last_3_chapter_urls=[
                        "https://luminousscans.com/legend-of-the-northern-blade-chapter-158/",
                        "https://luminousscans.com/legend-of-the-northern-blade-chapter-159/",
                        "https://luminousscans.com/legend-of-the-northern-blade-chapter-160/",
                    ],
                ),
                id_first=True,
                test_subject=LuminousScans
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://en.leviatanscans.com/manga/my-dad-is-too-strong/"),
                expected_result=ExpectedResult(
                    scanlator_name="leviatanscans",
                    manga_url="https://en.leviatanscans.com/manga/my-dad-is-too-strong/",
                    completed=False,
                    human_name="My Dad is Too Strong",
                    manga_id=default_id_func("https://en.leviatanscans.com/manga/my-dad-is-too-strong"),
                    curr_chapter_url="https://en.leviatanscans.com/manga/my-dad-is-too-strong/chapter-134/",
                    first_chapter_url="https://en.leviatanscans.com/manga/my-dad-is-too-strong/chapter-1/",
                    cover_image="https://en.leviatanscans.com/wp-content/uploads/2023/04/bannerMDTS.jpg",
                    last_3_chapter_urls=[
                        "https://en.leviatanscans.com/manga/my-dad-is-too-strong/chapter-132/",
                        "https://en.leviatanscans.com/manga/my-dad-is-too-strong/chapter-133/",
                        "https://en.leviatanscans.com/manga/my-dad-is-too-strong/chapter-134/",
                    ],
                ),
                test_subject=LeviatanScans
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://drakescans.com/series/my-disciples-are-all-big-villains/"),
                expected_result=ExpectedResult(
                    scanlator_name="drakescans",
                    manga_url="https://drakescans.com/series/my-disciples-are-all-big-villains/",
                    completed=False,
                    human_name="My Disciples Are All Big Villains",
                    manga_id=default_id_func("https://drakescans.com/series/my-disciples-are-all-big-villains"),
                    curr_chapter_url="https://drakescans.com/series/my-disciples-are-all-big-villains/chapter-82/",
                    first_chapter_url="https://drakescans.com/series/my-disciples-are-all-big-villains/chapter-1/",
                    cover_image="https://drakescans.com/wp-content/uploads/2022/12/V-193x278.jpg",
                    last_3_chapter_urls=[
                        "https://drakescans.com/series/my-disciples-are-all-big-villains/chapter-80/",
                        "https://drakescans.com/series/my-disciples-are-all-big-villains/chapter-81/",
                        "https://drakescans.com/series/my-disciples-are-all-big-villains/chapter-82/",
                    ],
                ),
                test_subject=DrakeScans
            ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://nitroscans.com/series/the-s-classes-that-i-raised/"),
                expected_result=ExpectedResult(
                    scanlator_name="nitroscans",
                    manga_url="https://nitroscans.com/series/the-s-classes-that-i-raised/",
                    completed=False,
                    human_name="The S-Classes That I Raised",
                    manga_id=default_id_func("https://nitroscans.com/series/the-s-classes-that-i-raised"),
                    curr_chapter_url="https://nitroscans.com/series/the-s-classes-that-i-raised/chapter-90/",
                    first_chapter_url="https://nitroscans.com/series/the-s-classes-that-i-raised/chapter-1/",
                    cover_image="https://nitroscans.com/wp-content/uploads/2022/06/The-S-Classes-That-I-Raised-193x278.jpg",
                    last_3_chapter_urls=[
                        "https://nitroscans.com/series/the-s-classes-that-i-raised/chapter-88/",
                        "https://nitroscans.com/series/the-s-classes-that-i-raised/chapter-89/",
                        "https://nitroscans.com/series/the-s-classes-that-i-raised/chapter-90/",
                    ],
                ),
                test_subject=NitroScans
            ),
            # TestCase(
            #     test_setup,
            #     test_data=TestInputData("https://mangapill.com/chapters/5284-10162000/omniscient-reader-chapter-162"),
            #     expected_result=ExpectedResult(
            #         scanlator_name="mangapill",
            #         manga_url="https://mangapill.com/manga/5284/omniscient-reader/",
            #         completed=False,
            #         human_name="Omniscient Reader",
            #         manga_id="5284",
            #         curr_chapter_url="https://mangapill.com/chapters/5284-10162000/omniscient-reader-chapter-162",
            #         first_chapter_url="https://mangapill.com/chapters/5284-10000000/omniscient-reader-chapter-0",
            #         cover_image="https://cdn.readdetectiveconan.com/file/mangapill/i/5284.jpeg",
            #         last_3_chapter_urls=[
            #             "https://mangapill.com/chapters/5284-10162000/omniscient-reader-chapter-162",
            #             "https://mangapill.com/chapters/5284-10161000/omniscient-reader-chapter-161",
            #             "https://mangapill.com/chapters/5284-10160000/omniscient-reader-chapter-160",
            #         ],
            #     ),
            #     id_first=True,
            #     test_subject=Mangapill
            # ),
            TestCase(
                test_setup,
                test_data=TestInputData("https://bato.to/series/106147/bad-thinking-diary-unofficial"),
                expected_result=ExpectedResult(
                    scanlator_name="bato.to",
                    manga_url="https://bato.to/series/106147/bad-thinking-diary-unofficial",
                    completed=False,
                    human_name="Bad Thinking Diary (unofficial)",
                    manga_id="106147",
                    curr_chapter_url="https://bato.to/chapter/2342882",
                    first_chapter_url="https://bato.to/chapter/1965357",
                    cover_image=(
                        "https://xfs-s105.batcg.org/thumb/W600/ampi/900"
                        "/900affca276584ddd39fbb82cb61891ac9eeb39f_597_778_126135.jpeg"
                    ),
                    last_3_chapter_urls=[
                        "https://bato.to/chapter/2319461",
                        "https://bato.to/chapter/2330320",
                        "https://bato.to/chapter/2342882",
                    ],
                ),
                id_first=True,
                test_subject=Bato
            )
        ]
        try:
            await run_tests(testCases)
            # await run_single_test(testCases[8])
        finally:
            await test_setup.bot.close()


    import asyncio

    asyncio.run(main())
