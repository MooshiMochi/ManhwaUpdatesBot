import asyncio
import logging
import os
import sys
from typing import Dict, Optional

from src.core import (
    CachedClientSession,
    CachedCurlCffiSession,
    Database,
)
from src.core.apis import APIManager, ComickAppAPI, MangaDexAPI
from src.utils import setup_logging, silence_debug_loggers

root_path = [x for x in sys.path if x.endswith("ManhwaUpdatesBot")][0]
logger = logging.getLogger()


class _ThirdProperties:
    url = ""


class User:
    @property
    def display_avatar(self):
        return _ThirdProperties()

    @property
    def display_name(self):
        return "Manhwa Updates"


# noinspection PyTypeChecker
class Bot:
    config: dict = None
    proxy_addr: Optional[str] = None

    def __init__(self, proxy_url: Optional[str] = None, scanlaors: dict = None):
        self.session = CachedClientSession(proxy=proxy_url)
        self.db = Database(self, database_name=os.path.join(root_path, "tests", "database.db"))
        self.mangadex_api = MangaDexAPI(self.session)
        self.comick_api = ComickAppAPI(self.session)
        self.curl_session = CachedCurlCffiSession(
            impersonate="chrome101",
            name="cache.curl_cffi",
            proxies={"http": proxy_url, "https": proxy_url},
        )
        self.logger = logging.getLogger("bot")
        self.user = User()
        self.apis: APIManager | None = None
        if scanlaors:
            self.load_scanlators(scanlaors)

    async def close(self):
        await self.curl_session.close()
        await self.session.close()

    async def __aenter__(self):
        await self.db.async_init()
        self.apis = APIManager(self, CachedClientSession(proxy=self.proxy_addr, name="cache.apis", trust_env=True))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        await self.apis.session.close() if self.apis else None

    def load_scanlators(self, scanlators: dict):
        for scanlator in scanlators.values():
            scanlator.bot = self

    @staticmethod
    async def log_to_discord(content, **kwargs):
        print(content)
        print(kwargs)


class TestCog:
    def __init__(self, bot):
        self.bot = bot
        self.rate_limiter = {}


def load_config() -> Dict:
    import yaml
    path = os.path.join(root_path, "tests", "config.yml")
    with open(path, "r") as f:
        config = yaml.safe_load(f)
    return config


def toggle_logging(name: str = "__main__") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())
    return logger


def fmt_proxy(username: str, password: str, ip: str, port: str) -> str:
    # noinspection HttpUrlsUsage
    return f"http://{username}:{password}@{ip}:{port}"


def init_scanlators(bot, scanlators: dict) -> None:
    for _name in scanlators:
        scanlators[_name].bot = bot


async def main():
    config = load_config()
    proxy_url = fmt_proxy(
        config["proxy"]["username"], config["proxy"]["password"], config["proxy"]["ip"], config["proxy"]["port"]
    )

    Bot.config = config
    Bot.proxy_addr = proxy_url

    # noinspection PyProtectedMember
    from src.core.scanlators import scanlators

    async with Bot(proxy_url=proxy_url) as bot:
        init_scanlators(bot, scanlators)
        key = "comick"
        url = "https://comick.io/comic/the-main-characters-that-only-i-know"
        query = "he"
        scanlator = scanlators[key]
        title = await scanlator.get_title(url)

        _id = await scanlator.get_id(url)
        all_chapters = await scanlator.get_all_chapters(url)
        status = await scanlator.get_status(url)
        synopsis = await scanlator.get_synopsis(url)
        cover = await scanlator.get_cover(url)
        fp_manga = await scanlator.get_fp_partial_manga()
        search_result = await scanlator.search(query)
        manga = await scanlator.make_manga_object(url)
        updates_result = await scanlator.check_updates(manga)
        #
        results = (
            f"Title: {title}", f"ID: {_id}", f"All Chapters: {all_chapters}", f"Status: {status}",
            f"Synopsis: {synopsis}", f"Cover: {cover}", f"FP Manhwa: {fp_manga}", f"Search: {search_result}",
            f"Manga obj: {manga}", f"Updates result: {updates_result}"
        )
        for result in results:
            print(result, "\n")

        res, = await scanlator.unload_manga([manga])
        print("Unloaded manhwa:", res)
        res2, = await scanlator.load_manga([res])
        print("Loaded manhwa:", res2)
        print(res2.last_chapter)


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    setup_logging(level=logging.DEBUG)
    silence_debug_loggers(
        logger,
        [
            "websockets.client",
            "aiosqlite",
            "discord.gateway",
            "discord.client",
            "discord.http",
            "discord.webhook.async_",
            "asyncio",
            "filelock"
        ]
    )
    asyncio.run(main())
