import asyncio
import logging
import os
import sys
from typing import Dict, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import CachedCurlCffiSession, Database
from src.core.apis import APIManager, ComickAppAPI, MangaDexAPI
from src.utils import setup_logging, silence_debug_loggers

root_path = [x for x in sys.path if x.endswith("ManhwaUpdatesBot")][0]
logger = logging.getLogger()

CONFIG: dict = {}


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
    config: dict = {}
    proxy_addr: Optional[str] = None

    def __init__(self, proxy_url: Optional[str] = None, scanlaors: dict = None):
        self.db = Database(self, database_name=os.path.join(root_path, "tests", "database.db"))

        if self.config["proxy"]["enabled"]:
            if self.config["proxy"]["username"] and self.config["proxy"]["password"]:
                self.proxy_addr = (
                    f"http://{self.config['proxy']['username']}:{self.config['proxy']['password']}@"  # noqa
                    f"{self.config['proxy']['ip']}:{self.config['proxy']['port']}"
                )
            else:
                self.proxy_addr = f"http://{self.config['proxy']['ip']}:{self.config['proxy']['port']}"  # noqa
        else:
            self.proxy_addr = None

        self.session = CachedCurlCffiSession(
            impersonate="chrome101",
            name="cache.curl_cffi",
            proxies={"http": proxy_url, "https": proxy_url},
        )

        self.apis = APIManager(self, CachedCurlCffiSession(
            impersonate="chrome101",
            name="cache.curl_cffi",
            proxies={"http": self.proxy_addr, "https": self.proxy_addr},
        ))

        self.mangadex_api = MangaDexAPI(self.apis)
        self.comick_api = ComickAppAPI(self.apis)
        self.logger = logging.getLogger("bot")
        self.user = User()
        if scanlaors:
            self.load_scanlators(scanlaors)

    async def close(self):
        await self.db.conn.close()
        await self.session.close()

    async def __aenter__(self):
        await self.db.async_init()
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
    if not CONFIG:
        raise Exception("Config not loaded!")
    if CONFIG["proxy"]["enabled"]:
        proxy_url = fmt_proxy(
            CONFIG["proxy"]["username"], CONFIG["proxy"]["password"], CONFIG["proxy"]["ip"], CONFIG["proxy"]["port"]
        )
    else:
        proxy_url = None

    Bot.config = CONFIG
    Bot.proxy_addr = proxy_url

    # noinspection PyProtectedMember
    from src.core.scanlators import scanlators

    async with Bot(proxy_url=proxy_url) as bot:
        init_scanlators(bot, scanlators)
        # for s in scanlators.values():
        #     print(s.name)
        key = "arvencomics"
        url = "https://arvencomics.com/comic/the-delusional-hunter-in-another-world/"
        query = "he"
        scanlator = scanlators[key]
        title = await scanlator.get_title(url);
        # print("Title:", title)
        _id = await scanlator.get_id(url);
        # print("ID:", _id)
        all_chapters = await scanlator.get_all_chapters(url);
        # print("All chapters:", all_chapters)
        status = await scanlator.get_status(url);
        # print("Status:", status)
        synopsis = await scanlator.get_synopsis(url);
        # print("Synopsis:", synopsis)
        cover = await scanlator.get_cover(url);
        # print("Cover:", cover)
        fp_manga = await scanlator.get_fp_partial_manga();
        # print("FP Manhwa:", fp_manga)
        if scanlator.json_tree.properties.supports_search:
            search_result = await scanlator.search(query);
        else:
            search_result = "Not supported"
        # print("Search:", search_result)
        manga = await scanlator.make_manga_object(url, load_from_db=False)
        # print("Manga obj:", manga)
        updates_result = await scanlator.check_updates(manga);
        # print("Updates result:", updates_result)

        results = (
            f"Title: {title}", f"ID: {_id}", f"URL: {manga.url}", f"All Chapters [{len(all_chapters)}]: {all_chapters}",
            f"Status: {status}",
            f"Synopsis: {synopsis}", f"Cover: {cover}", f"FP Manhwa [{len(fp_manga or [])}]: {fp_manga}",
            f"Search [{len(search_result or [])}]: {search_result}",
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
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    setup_logging(level=logging.DEBUG)
    CONFIG = load_config()
    silence_debug_loggers(
        logger,
        CONFIG.get("debug", False),
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
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    finally:
        loop.close()
