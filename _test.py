import asyncio
import hashlib
import logging
import sys
from typing import Dict, Optional

from src.core import CachedClientSession, CachedCurlCffiSession, ComickAppAPI, Database, MangaDexAPI
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
            impersonate="chrome101", name="cache.curl_cffi", proxies={"http": proxy_url, "https": proxy_url}
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
    with open("../config.yml", "r") as f:
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

    from src.core.scanners import Bato

    async with Bot(proxy_url=proxy_url) as bot:
        url = "https://bato.to/title/128011-hide-well-or-i-ll-see-your-xx"
        manga_id = await Bato.get_manga_id(bot, url)

        synopsis = await Bato.get_synopsis(bot, manga_id, url)
        print(synopsis)


async def test_ratelimit():
    config = load_config()
    proxy_url = fmt_proxy(**config["proxy"])

    Bot.config = config
    Bot.proxy_addr = proxy_url

    total = 0
    print("Beginning test...")
    async with Bot(proxy_url=proxy_url) as bot:
        while True:
            r = await bot.curl_session.get("https://reaperscans.com/comics/8556-the-novels-extra",
                                           impersonate="chrome101")
            if r.status_code == 429:
                print(f"Ratelimited! Total requests: {total}")
                break
            elif r.status_code != 200:
                print(f"Error! Status code: {r.status_code}. Total requests: {total}")
                break
            total += 1
            print(f"Total requests: {total}")


async def raw():
    time_string = "22 mins ago".strip()
    x = time_string_to_seconds(time_string)
    print(x)


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_ratelimit())
