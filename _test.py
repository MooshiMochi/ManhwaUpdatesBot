import asyncio
import hashlib
import logging
import sys
from typing import Dict, Optional

from src.core import (
    CachedClientSession,
    CachedCurlCffiSession,
    ComickAppAPI,
    Database,
    MangaDexAPI,
)
from src.core.scanners import SCANLATORS
from src.utils import time_string_to_seconds

# add the parent directory to the path
sys.path.append("..")


# noinspection PyTypeChecker
class Bot:
    config: dict = None
    proxy_addr: Optional[str] = None

    def __init__(self, proxy_url: Optional[str] = None):
        self.session = CachedClientSession(proxy=proxy_url)
        self.db = Database(self)
        self.mangadex_api = MangaDexAPI(self.session)
        self.comick_api = ComickAppAPI(self.session)
        self.curl_session = CachedCurlCffiSession(
            impersonate="chrome101",
            name="cache.curl_cffi",
            proxies={"http": proxy_url, "https": proxy_url},
        )
        self.logger = logging.getLogger("bot")

    async def close(self):
        self.curl_session.close()
        await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class TestCog:
    def __init__(self, bot):
        self.bot = bot
        self.SCANLATORS = SCANLATORS
        self.rate_limiter = {}


def default_id_func(manga_url: str) -> str:
    return hashlib.sha256(manga_url.encode()).hexdigest()


def load_config() -> Dict:
    import yaml

    with open("config.yml", "r") as f:
        config = yaml.safe_load(f)
    return config


def toggle_logging(name: str = "__main__") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())
    return logger


def fmt_proxy(username: str, password: str, ip: str, port: str, *args, **kwargs) -> str:
    return f"http://{username}:{password}@{ip}:{port}"


# noinspection PyTypeChecker
async def main():
    config = load_config()
    proxy_url = fmt_proxy(**config["proxy"])

    Bot.config = config
    Bot.proxy_addr = proxy_url

    from pprint import pprint
    from src.core.scanners import LeviatanScans

    async with Bot(proxy_url=proxy_url) as bot:
        url = "https://en.leviatanscans.com/manga/my-dad-is-too-strong-1/"
        result = await LeviatanScans.get_all_chapters(bot, "", url)
        pprint(result)


async def raw():
    time_string = "a few seconds ago".strip()
    x = time_string_to_seconds(time_string)
    print(x)


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(raw())
