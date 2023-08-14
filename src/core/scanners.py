from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import re

from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote_plus as url_encode
from src.static import Constants, RegExpressions
from src.utils import (
    get_url_hostname,
    replace_tag_with,
    write_to_discord_file,
    time_string_to_seconds,
    dict_remove_keys,
    is_from_stack_origin
)
from . import rate_limiter
from src.enums import Minutes

from .errors import MangaNotFound, URLAccessFailed
from .objects import ChapterUpdate, Chapter, ABCScan, Manga


class TritiniaScans(ABCScan):
    rx: re.Pattern = RegExpressions.tritinia_url
    icon_url = "https://tritinia.org/wp-content/uploads/2021/01/unknown.png"
    base_url = "https://tritinia.org"
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "tritinia"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @staticmethod
    def _ensure_manga_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(bot, manga)

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapter_container = soup.find_all("li", {"class": "wp-manga-chapter"})
            chapters: list[Chapter] = []

            for i, chap in enumerate(reversed(chapter_container)):
                chapter_tag = chap.find("a")
                chapter_url = chapter_tag["href"]
                chapter_text = chapter_tag.text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        headings, contents = status_container.find_all(
            "div", {"class": "summary-heading"}
        ), status_container.find_all("div", {"class": "summary-content"})
        for heading, content in zip(headings, contents):
            if (item_name := heading.find("h5")) is not None:
                if item_name.text.strip().lower() == "status":
                    status = content.text.strip().lower()
                    return (
                            status == "completed"
                            or status == "dropped"
                            or status == "canceled"
                    )
        return True

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "post-title"})
            title = title_div.find("h1")
            span_found = title.find("span")
            if span_found:
                span_found.decompose()
            return title.text.strip()

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis_div = soup.find("div", {"class": "summary__content"})
            synopsis = "\n\n".join([p.text.strip() for p in synopsis_div.find_all("p")])
            return synopsis

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img = soup.find("div", {"class": "summary_image"}).find("img")
            return img["data-src"]


class Manganato(ABCScan):
    rx: re.Pattern = RegExpressions.manganato_url
    icon_url = "https://chapmanganato.com/favicon.png"
    base_url = "https://chapmanganato.com"
    fmt_url = base_url + "/manga-{manga_id}"
    name = "manganato"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        synopsis_div = soup.find("div", {"class": "panel-story-info-description"})
        synopsis_div.find("h3").decompose()
        replace_tag_with(synopsis_div, "br", "\n")
        return synopsis_div.text.strip()

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("table", {"class": "variations-tableInfo"})
        status_labels = status_container.find_all(
            "td", {"class": "table-label"}, limit=5
        )
        status_values = status_container.find_all(
            "td", {"class": "table-value"}, limit=5
        )
        status = [
            (lbl.text.strip(), val.text.strip())
            for lbl, val in zip(status_labels, status_values)
            if lbl.text.strip() == "Status :"
        ][0][1]
        status = status.lower()
        return (
                status == "completed" or status == "dropped"
        )  # even though manganato doesn't have dropped series

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        text = resp.text

        if "404 - PAGE NOT FOUND" in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(resp.text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        title_div = soup.find("div", {"class": "story-info-right"})
        return title_div.find("h1").text.strip()

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")

        chapter_list_container = soup.find("div", {"class": "panel-story-chapter-list"})
        chapter_tags = chapter_list_container.find_all("a")
        chapters = []
        for i, chp_tag in enumerate(reversed(chapter_tags)):
            new_chapter_url = chp_tag["href"]
            new_chapter_text = chp_tag.text
            chapters.append(Chapter(new_chapter_url, new_chapter_text, i))
        return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        return cls.fmt_url.format(manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        img = soup.find("span", {"class": "info-image"}).find(
            "img", {"class": "img-loading"}
        )
        return img["src"] if img else None


class Toonily(ABCScan):
    rx: re.Pattern = RegExpressions.toonily_url
    icon_url = "https://toonily.com/wp-content/uploads/2020/01/cropped-toonfavicon-1-192x192.png"
    base_url = "https://toonily.com"
    fmt_url = base_url + "/webtoon/{manga_url_name}"
    name = "toonily"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.FIVE
    )  # 20s interval

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        url_name = cls.rx.search(manga_url).groupdict().get("url_name", None)
        if not url_name:
            raise MangaNotFound(manga_url)
        headers = super()._make_headers(bot, manga_id, manga_url)
        used_headers = ["User-Agent"]
        return {k: v for k, v in headers.items() if k in used_headers}

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        resp = await bot.curl_session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")

        synopsis_div = soup.find("div", {"class": "summary__content"})
        replace_tag_with(synopsis_div, "br", "\n")
        synopsis = "\n".join([x.text.strip() for x in synopsis_div.find_all("p")])
        return synopsis

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await bot.curl_session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")

        chapter_list_container = soup.find(
            "ul", {"class": "main version-chap no-volumn"}  # noqa
        )
        chapter_tags = chapter_list_container.find_all("a")
        chapters: list[Chapter] = []
        for i, chp_tag in enumerate(reversed(chapter_tags)):
            new_chapter_url = chp_tag["href"]
            new_chapter_text = chp_tag.text
            chapters.append(Chapter(new_chapter_url, new_chapter_text, i))
        return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        container_items = status_container.find_all(
            "div", {"class": "post-content_item"}
        )

        for item in container_items:
            heading_div = item.find("div", {"class": "summary-heading"})
            if heading_div.find("h5").text.strip().lower() == "status":
                status = (
                    item.find("div", {"class": "summary-content"}).text.strip().lower()
                )
                return status == "completed" or status == "canceled"
        else:  # no break/return
            return False

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        resp = await bot.curl_session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        title_div = soup.find("div", {"class": "post-title"})
        title = title_div.find("h1")
        span_found = title.find("span")
        if span_found:
            span_found.decompose()
        return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        cover_image = soup.find("div", {"class": "summary_image"}).find("img")
        image_url = cover_image["data-src"].strip()
        return image_url


class MangaDex(ABCScan):
    rx: re.Pattern = RegExpressions.mangadex_url
    icon_url = "https://mangadex.org/favicon.ico"
    base_url = "https://mangadex.org"
    fmt_url = base_url + "/title/{manga_id}"
    chp_url_fmt = base_url + "/chapter/{chapter_id}"
    name = "mangadex"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    ).disable()  # disabled, handled in the API

    # For mangadex, the 'last_known_status' variable is set in the API class @ src/core/mangadexAPI.py

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    def _ensure_chp_url_was_in_chapters_list(
            cls, last_chapter_url: str, chapters_list: list[dict[str, str]]
    ) -> bool:
        for chp in chapters_list:
            chp_id = chp["id"]
            curr_chp_url = cls.chp_url_fmt.format(chapter_id=chp_id)
            if curr_chp_url == last_chapter_url:
                return True
        return False

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        synopsis = await bot.mangadex_api.get_synopsis(manga_id)
        if synopsis:
            return synopsis
        else:
            return "None available"

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        chapters = await bot.mangadex_api.get_chapters_list(manga_id)
        if chapters:
            return [
                Chapter(
                    cls.chp_url_fmt.format(chapter_id=chp["id"]),
                    f'Chapter {chp["attributes"]["chapter"]}',
                    i,
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return None

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        manga = await bot.mangadex_api.get_manga(manga_id)
        status = manga["data"]["attributes"]["status"].lower()
        return status == "completed" or status == "cancelled"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await bot.mangadex_api.get_manga(manga_id)
        return manga["data"]["attributes"]["title"]["en"]

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        return super()._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str:
        if manga_id is None and manga_url is not None:
            manga_id = await cls.get_manga_id(bot, manga_url)
        return cls.fmt_url.format(manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await bot.mangadex_api.get_manga(manga_id)
        cover_id = [
            x["id"] for x in manga["data"]["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await bot.mangadex_api.get_cover(manga["data"]["id"], cover_id)
        return cover_url

    @classmethod
    async def search(
            cls, bot: MangaClient, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        results = await bot.mangadex_api.search(title=query, limit=1)
        if not results or not results["data"]:
            return None
        data = results["data"][0]
        manga_id = data["id"]
        manga_obj = await cls.make_manga_object(bot, manga_id, await cls.fmt_manga_url(bot, manga_id, ""))
        if as_em is False:
            return manga_obj
        else:
            synopsis_text = manga_obj.synopsis
            if len(synopsis_text) > 1024:
                extra = f"... [(read more)]({manga_obj.url})"
                len_url = len(extra)
                synopsis_text = synopsis_text[: 1024 - len_url] + extra

            first_chapter = manga_obj.available_chapters[0] if len(manga_obj.available_chapters) > 0 else "N/A"
            last_chapter = manga_obj.available_chapters[-1] if len(manga_obj.available_chapters) > 0 else "N/A"

            desc = f"**Num of Chapters:** {len(manga_obj.available_chapters)}\n"
            desc += "**Status:** " + ("Completed\n" if manga_obj.completed else "Ongoing\n")
            desc += f"**Latest Chapter:** {last_chapter}\n"
            desc += f"**First Chapter:** {first_chapter}"
            desc += f"**Scanlator:** {manga_obj.scanlator}"

            return (
                discord.Embed(
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


class FlameScans(ABCScan):
    rx: re.Pattern = RegExpressions.flamescans_url
    icon_url = (
        "https://flamescans.org/wp-content/uploads/2021/03/cropped-fds-1-192x192.png"
    )
    base_url = "https://flamescans.org"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "flamescans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @staticmethod
    def _fix_chapter_url(chapter_url: str) -> str:
        """This will add the ID to the URL all the time for consistency.
        Mainly doing this bc flamescans are cheeky and are changing the URLs from time to time...
        """
        pattern1 = re.compile(r"flamescans\.org/\d{9,}-", re.MULTILINE)
        pattern2 = re.compile(r"flamescans\.org/series/\d{9,}-", re.MULTILINE)

        if pattern1.search(chapter_url):
            return pattern1.sub("flamescans.org/", chapter_url)
        elif pattern2.search(chapter_url):
            return pattern2.sub("flamescans.org/series/", chapter_url)
        return chapter_url

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            replace_tag_with(synopsis, "strong", "**", closing=True)
            replace_tag_with(synopsis, "br", "\n")
            return "\n".join([x.text.strip() for x in synopsis.find_all("p")])

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find_all("a")
            chapters: list[Chapter] = []

            for i, chapter in enumerate(reversed(chapter_list)):
                chapter_url = chapter["href"]
                chapter_url = cls._fix_chapter_url(chapter_url)

                chapter_title = chapter.find(
                    "span", {"class": "chapternum"}
                ).text.strip()

                chapters.append(Chapter(chapter_url, chapter_title, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        status_div = soup.find("div", {"class": "status"})
        status = status_div.find("i").text.strip().lower()
        return status == "completed" or status == "dropped"

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL:"
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return soup.find("h1", {"class": "entry-title"}).text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            cover_image = soup.find(
                "div", {"class": "thumb", "itemprop": "image"}
            ).find("img")
            return cover_image["src"] if cover_image else None


class Asura(ABCScan):
    rx: re.Pattern = RegExpressions.asura_url
    # base_url = "https://asura.gg"
    base_url = "https://asura.nacm.xyz"  # TODO: temp asura URL
    icon_url = (
        f"{base_url}/wp-content/uploads/2021/03/cropped-Group_1-1-192x192.png"  # noqa
    )
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "asura"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.ONE
    )  # 4s interval
    NOT_FOUND_IMG_URL = (
        f"{base_url}/wp-content/themes/mangastream/assets/images/404.png"  # noqa
    )

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        request_url = _manga_request_url or manga.url
        try:
            all_chapters = await cls.get_all_chapters(bot, manga.id, request_url)
            completed: bool = await cls.is_series_completed(bot, manga.id, manga.url)
            cover_url: str = await cls.get_cover_image(bot, manga.id, manga.url)
            if all_chapters is None:
                return ChapterUpdate([], cover_url, completed)
            new_chapters: list[Chapter] = [
                chapter for chapter in all_chapters if chapter.index > manga.last_chapter.index
            ]
            return ChapterUpdate(
                new_chapters,
                cover_url,
                completed,
                [
                    {
                        "embed": cls._create_chapter_embed(
                            "Asura Scans",
                            Constants.no_img_available_url,
                            manga.human_name,
                            chapter.url,
                            chapter.name,
                        ),
                    }
                    for chapter in new_chapters
                ],
            )
        except (ValueError, AttributeError) as e:
            await cls.report_error(bot, e, request_url=request_url)
        except Exception as e:
            raise e

    @staticmethod
    def _fix_chapter_url(chapter_url: str) -> str:
        """This will add the ID to the URL all the time for consistency.
        Mainly doing this bc asura are cheeky and are changing the URLs from time to time...
        """
        # pattern1 = re.compile(r"asura\.gg/\d{9,}-", re.MULTILINE)
        # pattern2 = re.compile(r"asura\.gg/manga/\d{9,}-", re.MULTILINE)

        pattern1 = re.compile(r"asura\.nacm\.xyz/\d{9,}-", re.MULTILINE)  # TODO: temp asura URL
        pattern2 = re.compile(r"asura\.nacm\.xyz/\d{9,}-", re.MULTILINE)  # TODO: temp asura URL

        if pattern1.search(chapter_url):
            # return pattern1.sub("asura.gg/", chapter_url)
            return pattern1.sub("asura.nacm.xyz/", chapter_url)  # TODO: temp asura URL  # noqa
        elif pattern2.search(chapter_url):
            # return pattern2.sub("asura.gg/manga/", chapter_url)
            return pattern2.sub("asura.nacm.xyz/manga/", chapter_url)  # TODO: temp asura URL  # noqa
        return chapter_url

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text
        if cls.NOT_FOUND_IMG_URL in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(text, "html.parser")
        synopsis = soup.find(
            "div", {"class": "entry-content", "itemprop": "description"}
        )
        return synopsis.text.strip().replace("&nbsp;", "")

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text
        if cls.NOT_FOUND_IMG_URL in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "eplister"})
        chapters_list = chapter_list_container.find_all("a")
        chapters: list[Chapter] = []
        for i, chapter in enumerate(reversed(chapters_list)):
            chapter_url = chapter["href"]
            chapter_url = cls._fix_chapter_url(chapter_url)
            chapter_text = chapter.find("span", {"class": "chapternum"}).text.strip()
            chapters.append(Chapter(chapter_url, chapter_text, i))
        return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div = soup.find("div", {"class": "imptdt"})  # noqa
        status = status_div.find("i").text.strip()
        return status.lower() == "completed" or status.lower() == "dropped"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text
        if cls.NOT_FOUND_IMG_URL in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1", {"class": "entry-title"})
        return title_tag.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text
        if cls.NOT_FOUND_IMG_URL in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text
        if cls.NOT_FOUND_IMG_URL in text:
            raise MangaNotFound(manga_url)

        soup = BeautifulSoup(text, "html.parser")
        cover_image = soup.find("div", {"class": "thumb", "itemprop": "image"}).find(
            "img"
        )
        return cover_image["src"] if cover_image else None


class Aquamanga(ABCScan):
    rx: re.Pattern = RegExpressions.aquamanga_url
    icon_url = "https://aquamanga.com/wp-content/uploads/2021/03/cropped-cropped-favicon-1-192x192.png"
    base_url = "https://aquamanga.com"
    fmt_url = base_url + "/read/{manga_url_name}"
    name = "aquamanga"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        url_name = cls.rx.search(manga_url).groupdict().get("url_name", None)
        if not url_name:
            raise MangaNotFound(manga_url)
        headers = super()._make_headers(bot, manga_id, manga_url)
        used_headers = [
            ":Authority", ":Method", ":Path", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Pragma", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest",
            "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", "Upgrade-Insecure-Requests", "User-Agent",
        ]
        updated_headers = {
            ":Path": f"/read/{url_name}/",
        }
        headers |= updated_headers
        headers = dict_remove_keys(headers, [k for k in headers if k not in used_headers])
        return headers

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        request_url = _manga_request_url or manga.url
        try:
            all_chapters = await cls.get_all_chapters(bot, manga.id, request_url)
            completed: bool = await cls.is_series_completed(bot, manga.id, manga.url)
            cover_url: str = await cls.get_cover_image(bot, manga.id, manga.url)
            if all_chapters is None:
                return ChapterUpdate([], cover_url, completed)
            new_chapters: list[Chapter] = [
                chapter
                for chapter in all_chapters
                if chapter.index > manga.last_chapter.index
            ]
            return ChapterUpdate(
                new_chapters,
                cover_url,
                completed,
                [
                    {
                        "embed": cls._create_chapter_embed(
                            "Aquamanga",
                            Constants.no_img_available_url,
                            manga.human_name,
                            chapter.url,
                            chapter.name,
                        )
                    }
                    for chapter in new_chapters
                ],
            )
        except (ValueError, AttributeError) as e:
            await cls.report_error(bot, e, request_url=request_url)
        except Exception as e:
            raise e

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            synopsis = soup.find("div", {"class": "summary__content"})
            synopsis.find("center").decompose()
            for x in synopsis.find_all("p", limit=2):
                x.decompose()
            return (
                "\n\n".join([x.text.strip() for x in synopsis.find_all("p")])
                .replace("&nbsp;", "")
                .strip()
            )

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            chapter_list_container = soup.find(
                "div", {"class": "listing-chapters_wrap"}
            )
            chapters_list = chapter_list_container.find_all("a", {"class": ""})
            chapters = []
            for i, chapter in enumerate(reversed(chapters_list)):
                chapter_url = chapter["href"]
                chapter_text = chapter.text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div_container = soup.find("div", {"class": "post-status"})
        status_div = status_div_container.find("div", {"class": "summary-content"})
        status = status_div.text.strip().lower()
        return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            title_container = soup.find("div", {"class": "post-title"})
            title = title_container.find("h1")
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            cover_img = soup.find("div", {"class": "summary_image"}).find("img")
            return cover_img["src"]


class ReaperScans(ABCScan):
    rx: re.Pattern = RegExpressions.reaperscans_url
    icon_url = "https://reaperscans.com/images/icons/310x310.png"
    base_url = "https://reaperscans.com"
    fmt_url = base_url + "/comics/{manga_id}-{manga_url_name}"
    name = "reaperscans"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.FIVE
    )  # 20s interval

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        request_url = _manga_request_url or manga.url
        all_chapters = await cls.get_all_chapters(bot, manga.id, request_url, page=0)
        completed: bool = await cls.is_series_completed(bot, manga.id, request_url)
        cover_url: str = await cls.get_cover_image(bot, manga.id, request_url)

        if all_chapters is None:
            return ChapterUpdate([], cover_url, completed)
        new_chapters: list[Chapter] = [
            chapter
            for chapter in all_chapters
            if chapter.index > manga.last_chapter.index
        ]

        return ChapterUpdate(
            new_chapters,
            cover_url,
            completed,
            [
                {
                    "embed": cls._create_chapter_embed(
                        "Reaper Scans",
                        Constants.no_img_available_url,
                        manga.human_name,
                        chapter.url,
                        chapter.name,
                    ),
                }
                for chapter in new_chapters
            ],
        )

    @staticmethod
    def _bs_total_chapters_available(soup: BeautifulSoup) -> int:
        status_container = soup.find("dl", {"class": "mt-2"})
        _type, content = status_container.find_all("dd"), status_container.find_all(
            "dt"
        )
        for _type_element, content_element in zip(_type, content):
            if content_element.text.strip().lower() == "total chapters":
                status = _type_element.text.strip()
                return int(status)
        else:
            raise Exception("Failed to find source status.")

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        synopsis = soup.find(
            "p",
            {
                "tabindex": "0",
                "class": "focus:outline-none prose lg:prose-sm dark:text-neutral-500 mt-3 w-full",
            },
        )
        return synopsis.text.strip()

    @classmethod
    async def get_chapters_on_page(
            cls, bot: MangaClient, manga_url: str, *, page: int | None = None
    ) -> tuple[list[Chapter] | None, int]:
        """
        Returns a tuple of (list of chapters [descending order], max number of chapters there are)
        for the given manga page.

        Args:
            bot: MangaClient - the bot instance
            manga_url: str - the manga url
            page: int | None - the page number to get chapters from. If None, get all chapters

        Returns:
            tuple[list[Chapter] | None, int] - the list of chapters and max number of chapters there are
        """
        if (
                page is not None and page > 1
        ):  # by default, no param = page 1, so we only consider page 2+
            resp = await bot.curl_session.get(manga_url.rstrip("/") + f"?page={page}")
        else:
            resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})

        chapters_container_parent = chapter_list_container.find_parent(
            "div",
            {
                "class": "focus:outline-none max-w-6xl bg-white dark:bg-neutral-850 rounded mt-6"
            },
        )
        if chapters_container_parent is None:
            bot.logger.warning(
                f"Could not fetch the chapters on page {page} for {manga_url}"
            )
            return None, cls._bs_total_chapters_available(soup)
        chapters_list = chapter_list_container.find_all("a")

        index_shift = 0
        if (
                pagination_container := chapters_container_parent.find(
                    "nav", {"role": "navigation"}
                )
        ) is not None:
            pagination_p = pagination_container.find("p")
            nums = list(
                map(
                    lambda x: int(x.text),
                    pagination_p.find_all("span", {"class": "font-medium"}),
                )
            )
            index_shift = nums[2] - nums[0] - len(chapters_list) + 1

        return (
            [
                Chapter(
                    chapter["href"], chapter.find("p").text.strip(), index_shift + i
                )
                for i, chapter in enumerate(reversed(chapters_list))
            ],
            cls._bs_total_chapters_available(soup),
        )

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str, *, page: int | None = None
    ) -> list[Chapter] | None:
        if page is not None and page == 0:
            return (await cls.get_chapters_on_page(bot, manga_url, page=page))[0]
        else:
            max_chapters = float("inf")
            chapters: list[Chapter] = []
            while len(chapters) < max_chapters:
                await asyncio.sleep(1)  # add some delay to reduce rate-limits
                next_page_chapters, max_chapters = await cls.get_chapters_on_page(
                    bot, manga_url, page=page
                )
                if next_page_chapters is None:
                    break
                chapters[:0] = next_page_chapters
                page = (page or 1) + 1
            if len(chapters) < max_chapters:
                # fill in the missing chapters
                chapters_to_fill = [
                    Chapter(manga_url, f"Chapter {i + 1}", i)
                    for i in range(max_chapters - len(chapters))
                ]
                chapters[:0] = chapters_to_fill
            return sorted(chapters, key=lambda x: x.index)

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})
        chapters_list = chapter_list_container.find_all("a")
        chapters = []
        for i, chapter in enumerate(reversed(chapters_list)):
            chapter_url = chapter["href"]
            chapter_text = chapter.find("p").text.strip()
            chapters.append(Chapter(chapter_url, chapter_text, i))

        last_chapter = chapters[-1]
        total_chapters = cls._bs_total_chapters_available(soup)
        if total_chapters is not None and total_chapters != len(chapters):
            return Chapter(last_chapter.url, last_chapter.name, total_chapters - 1)
        return last_chapter

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("dl", {"class": "mt-2"})
        _type, content = status_container.find_all("dd"), status_container.find_all(
            "dt"
        )
        for _type_element, content_element in zip(_type, content):
            if content_element.text.strip().lower() == "release status":
                status = _type_element.text.strip()
                return status.lower() == "completed" or status.lower() == "dropped"
        else:
            raise Exception("Failed to find source status.")

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1")
        return title_tag.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str:
        if manga_id is None and manga_url is not None:
            manga_id = await cls.get_manga_id(bot, manga_url)
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_id=manga_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(manga_url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        cover_div = soup.find("div", {"class": "transition"})
        cover_image = cover_div.find("img")
        return cover_image["src"] if cover_image else None


class AnigliScans(ABCScan):
    rx: re.Pattern = RegExpressions.anigliscans_url
    icon_url = "https://anigliscans.com/wp-content/uploads/2022/07/cropped-Untitled671_20220216124756-192x192.png"
    base_url = "https://anigliscans.com"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "anigliscans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        url_name = cls.rx.search(manga_url).groupdict().get("url_name", None)
        if not url_name:
            raise MangaNotFound(manga_url)
        headers = super()._make_headers(bot, manga_id, manga_url)
        used_headers = [
            ":Authority", ":Method", ":Path", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Pragma", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest",
            "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", "Upgrade-Insecure-Requests", "User-Agent",
        ]
        updated_headers = {
            ":Path": f"/series/{url_name}/",
        }
        headers |= updated_headers
        headers = dict_remove_keys(headers, [k for k in headers if k not in used_headers])
        return headers

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis_container = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            synopsis = synopsis_container.find_all("p")
            return "\n".join([x.text.strip() for x in synopsis])

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find_all("a")
            all_chapters: list[Chapter] = []

            for i, chapter in enumerate(reversed(chapter_list)):
                chapter_url = chapter["href"]

                chapter_text = chapter.find("span", {"class": "chapternum"}).text

                new_chapter = Chapter(chapter_url, chapter_text, i)
                all_chapters.append(new_chapter)
            return all_chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "tsinfo"})  # noqa
        status_tag = status_container.find("div", {"class": "imptdt"})  # noqa
        status = status_tag.find("i").text.strip().lower()
        return status == "completed" or status == "dropped"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_tag = soup.find("h1", {"class": "entry-title"})
            return title_tag.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            cover_image = soup.find(
                "div", {"class": "thumb", "itemprop": "image"}
            ).find("img")
            return cover_image["src"] if cover_image else None


class Comick(ABCScan):
    rx: re.Pattern = RegExpressions.comick_url
    icon_url = "https://comick.app/static/icons/unicorn-256_maskable.png"
    base_url = "https://comick.app"
    fmt_url = base_url + "/comic/{manga_url_name}?lang=en"
    chp_url_fmt = base_url + "/comic/{manga_url_name}/{chapter_id}"
    name = "comick"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    ).disable()  # rate-limits handled by the API implementation in ./comickAPI.py

    # For comick, the 'last_known_status' variable is set in the Comick api @ src/core/comickAPI.py

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        return await bot.comick_api.get_synopsis(manga_id)

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        chapters = await bot.comick_api.get_chapters_list(manga_id)
        if chapters:
            url_name = cls.rx.search(manga_url).groupdict()["url_name"]
            return [
                Chapter(
                    cls.chp_url_fmt.format(
                        manga_url_name=url_name, chapter_id=chp["hid"]
                    ),
                    f'Chapter {chp["chap"]}',
                    i,
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return None

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await bot.comick_api.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return None
        return manga["comic"]["title"]

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_manga_id func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
            manga_id = re.search(r"\"hid\":\"([^\"]+)\"", await resp.text()).group(1)
            return manga_id

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        manga = await bot.comick_api.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return False
        return manga["comic"]["status"] == 2

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        return await bot.comick_api.get_cover(manga_id)

    @classmethod
    async def search(
            cls, bot: MangaClient, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        result: list[dict] = await bot.comick_api.search(query, limit=1)  # noqa
        if not result: return None  # noqa
        manga_obj = await cls.make_manga_object(
            bot,
            manga_id=result[0]["hid"],
            manga_url=f'https://comick.app/comic/{result[0]["slug"]}',
        )

        if as_em is False:
            return manga_obj
        else:
            synopsis_text = manga_obj.synopsis
            if len(synopsis_text) > 1024:
                extra = f"... [(read more)]({manga_obj.url})"
                len_url = len(extra)
                synopsis_text = synopsis_text[: 1024 - len_url] + extra

            first_chapter = manga_obj.available_chapters[0] if len(manga_obj.available_chapters) > 0 else "N/A"
            last_chapter = manga_obj.available_chapters[-1] if len(manga_obj.available_chapters) > 0 else "N/A"

            desc = f"**Num of Chapters:** {len(manga_obj.available_chapters)}\n"
            desc += "**Status:** " + ("Completed\n" if manga_obj.completed else "Ongoing\n")
            desc += f"**Latest Chapter:** {last_chapter}\n"
            desc += f"**First Chapter:** {first_chapter}"

            return (
                discord.Embed(
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


class VoidScans(ABCScan):
    rx: re.Pattern = RegExpressions.voidscans_url
    icon_url = "https://void-scans.com/wp-content/uploads/cropped-cropped-weblogo-1-2-192x192.png"
    base_url = "https://void-scans.com"
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "voidscans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.THIRTY
    )  # 3s interval

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        synopsis_div = soup.find(
            "div", {"class": "entry-content", "itemprop": "description"}
        )
        synopsis_tags = synopsis_div.find_all("p")
        return "\n".join(
            [
                tag.text.strip()
                for tag in synopsis_tags
                if not tag.text.startswith("[metaslider id")
            ]
        )

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        chapters = soup.find("div", {"class": "eplister"}).find_all("a")

        return [
            Chapter(
                chapter["href"], chapter.find("span", {"class": "chapternum"}).text, i
            )
            for i, chapter in enumerate(reversed(chapters))
        ]

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(bot, manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(manga_url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.find("h1", {"class": "entry-title"}).text

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str | None:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                bot,
                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            return False

        soup = BeautifulSoup(resp.text, "html.parser")
        status_div = soup.find("div", {"class": "imptdt"})  # noqa
        status = status_div.find("i").text.strip().lower()
        return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            return await cls.report_error(
                bot,
                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        img_div = soup.find("div", {"class": "thumb"})
        return img_div.find("img")["src"]


class LuminousScans(ABCScan):
    rx: re.Pattern = RegExpressions.luminousscans_url
    icon_url = "https://luminousscans.com/wp-content/uploads/2021/12/cropped-logo.png"
    base_url = "https://luminousscans.com"
    fmt_url = base_url + "/series/{manga_id}-{manga_url_name}"
    name = "luminousscans"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval
    NOT_FOUND_IMG_URL = (
        f"{base_url}/wp-content/themes/mangareader/assets/images/404.png"  # noqa
    )

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)
            text = await resp.text()
            if cls.NOT_FOUND_IMG_URL in text:
                raise MangaNotFound(manga_url)

            soup = BeautifulSoup(text, "html.parser")
            synopsis = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            if cls.NOT_FOUND_IMG_URL in text:
                raise MangaNotFound(manga_url)

            soup = BeautifulSoup(text, "html.parser")
            chapters = soup.find("div", {"class": "eplister"}).find_all("a")

            return [
                Chapter(
                    chapter["href"],
                    chapter.find("span", {"class": "chapternum"}).text,
                    i,
                )
                for i, chapter in enumerate(reversed(chapters))
            ]

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(bot, manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            if cls.NOT_FOUND_IMG_URL in text:
                raise MangaNotFound(manga_url)

            soup = BeautifulSoup(text, "html.parser")
            return soup.find("h1", {"class": "entry-title"}).text

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str | None:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            if cls.NOT_FOUND_IMG_URL in text:
                raise MangaNotFound(manga_url)

            soup = BeautifulSoup(text, "html.parser")
            status_div = soup.find("div", {"class": "imptdt"})  # noqa
            status = status_div.find("i").text.strip().lower()
            return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_id=manga_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            if cls.NOT_FOUND_IMG_URL in text:
                raise MangaNotFound(manga_url)

            soup = BeautifulSoup(text, "html.parser")
            img_div = soup.find("div", {"class": "thumb"})
            return img_div.find("img")["src"]

    @classmethod
    async def search(
            cls, bot: MangaClient, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with bot.session.get(cls.base_url, params=params) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"class": "listupd"})  # noqa
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            manga_id = await cls.get_manga_id(bot, result_manga_url)
            manga_url = await cls.fmt_manga_url(bot, manga_id, result_manga_url)

            manga_obj = await cls.make_manga_object(bot, manga_id, manga_url)

            if as_em is False:
                return manga_obj
            else:
                synopsis_text = manga_obj.synopsis
                if len(synopsis_text) > 1024:
                    extra = f"... [(read more)]({manga_obj.url})"
                    len_url = len(extra)
                    synopsis_text = synopsis_text[: 1024 - len_url] + extra

                first_chapter = manga_obj.available_chapters[0] if len(manga_obj.available_chapters) > 0 else "N/A"
                last_chapter = manga_obj.available_chapters[-1] if len(manga_obj.available_chapters) > 0 else "N/A"

                desc = f"**Num of Chapters:** {len(manga_obj.available_chapters)}\n"
                desc += "**Status:**" + ("Completed\n" if manga_obj.completed else "Ongoing\n")
                desc += f"**Latest Chapter:** {last_chapter}\n"
                desc += f"**First Chapter:** {first_chapter}"

                return (
                    discord.Embed(
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


class LeviatanScans(ABCScan):
    rx: re.Pattern = RegExpressions.leviatanscans_url
    icon_url = "https://en.leviatanscans.com/wp-content/uploads/2023/04/cropped-isotiponegro-192x192.png"
    base_url = "https://en.leviatanscans.com"
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "leviatanscans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @staticmethod
    def _ensure_manga_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis_div = soup.find("div", {"class": "manga-about manga-info"})
            synopsis = synopsis_div.find("p")
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapters = soup.find("div", {"class": "listing-chapters_wrap"}).find_all(
                "a"
            )

            return [
                Chapter(chapter["href"], chapter.text, i)
                for i, chapter in enumerate(reversed(chapters))
            ]

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(bot, manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return soup.find("div", {"class": "post-title"}).find("h1").text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str | None:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            release_dates = soup.find("ul", {"class": "main"}).find_all(
                "span", {"class": "chapter-release-date"}
            )
            date_strings = [_date.find("i").text for _date in release_dates]
            if date_strings:
                date_to_check = date_strings[0]
                timestamp = time_string_to_seconds(date_to_check)
                if (
                        datetime.now().timestamp() - timestamp
                        > bot.config["constants"]["time-for-manga-to-be-considered-stale"]
                ):
                    return True
            return False

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img_div = soup.find("div", {"class": "summary_image"})
            return img_div.find("img")["src"].strip()


class DrakeScans(ABCScan):
    rx: re.Pattern = RegExpressions.drakescans_url
    icon_url = "https://i0.wp.com/drakescans.com/wp-content/uploads/2022/02/cropped-Logo_Discord-3.png"
    base_url = "https://drakescans.com"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "drakescans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        url_name = cls.rx.search(manga_url).groupdict().get("url_name", None)
        if not url_name:
            raise MangaNotFound(manga_url)
        headers = super()._make_headers(bot, manga_id, manga_url)
        used_header_keys = [
            ":Authority", ":Method", ":Path", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Content-Length", "Origin", "Pragma", "Referer", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile",
            "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User",
            "Upgrade-Insecure-Requests", "User-Agent" "X-Requested-With"
        ]
        updated_headers = {
            ":Path": f"/series/{url_name}/",
            "Origin": cls.base_url,
            "Referer": cls.base_url + f"/series/{url_name}/",
        }
        to_ajax_endpoint = is_from_stack_origin(class_name=cls.__name__, function_name="get_all_chapters")
        # if from ajax endpoint
        if to_ajax_endpoint:
            updated_headers |= {
                ":Method": "POST", "Accept": "*/*", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
            }
            updated_headers[":Path"] += "ajax/chapters/"
            used_header_keys = list(set(used_header_keys) - {"Sec-Fetch-User", "Upgrade-Insecure-Requests"})
        else:  # normal endpoint
            used_header_keys = list(set(used_header_keys) - {"Content-Length", "Origin", "Referer", "X-Requested-With"})
        updated_headers = {key: value for key, value in updated_headers.items() if key in used_header_keys}
        headers.update(updated_headers)
        headers = dict_remove_keys(headers, [key for key in headers if key not in used_header_keys])
        return headers

    @staticmethod
    def _ensure_manga_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(bot, manga)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return (
                soup.find("div", {"class": "summary__content"}).find("p").text.strip()
            )

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.post(
                cls._ensure_manga_url(manga_url), headers=cls._make_headers(bot, manga_id, manga_url)
        ) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapter_container = soup.find_all("li", {"class": "wp-manga-chapter"})
            chapters: list[Chapter] = []

            for i, chap in enumerate(reversed(chapter_container)):
                chapter_tag = chap.find("a")
                chapter_url = chapter_tag["href"]
                chapter_text = chapter_tag.text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        status_div = status_container.find_all("div", {"class": "post-content_item"})[1]
        status = status_div.find("div", {"class": "summary-content"})
        status = status.text.strip().lower()

        status_title = soup.find("span", {"class": "manga-title-badges"})
        if status_title:
            status_title = status_title.text.strip().lower()
            return (
                    status_title == "completed"
                    or status_title == "dropped"
                    or status_title == "canceled"
                    or status_title == "cancelled"
            )

        return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise MangaNotFound(manga_url=manga_url)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                return await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "post-title"})
            title = title_div.find("h1")
            span_found = title.find("span")
            if span_found:
                span_found.decompose()
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                return await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img = soup.find("div", {"class": "summary_image"}).find("img")
            return img["src"]


class Mangabaz(ABCScan):
    rx: re.Pattern = RegExpressions.mangabaz_url
    icon_url = "https://mangabaz.net/wp-content/uploads/2023/06/YT-Logo.png"
    base_url = "https://mangabaz.net"
    fmt_url = base_url + "/mangas/{manga_url_name}"
    name = "mangabaz"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @staticmethod
    def _ensure_manga_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(bot, manga)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(cls._ensure_manga_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            synopsis_div = soup.find(
                "div", {"class": ["summary__content", "show-more"]}
            )
            replace_tag_with(synopsis_div, "strong", "**", closing=True)
            return "\n".join(
                [
                    p.text.strip()
                    for p in synopsis_div.find_all("p")
                    if p.text.strip() != "&nbsp;"
                ]
            )

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapter_container = soup.find_all("li", {"class": "wp-manga-chapter"})
            chapters: list[Chapter] = []

            for i, chap in enumerate(reversed(chapter_container)):
                chapter_tag = chap.find("a")
                chapter_url = chapter_tag["href"]
                chapter_text = chapter_tag.text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        container_items = status_container.find_all(
            "div", {"class": "post-content_item"}
        )

        for item in container_items:
            heading_div = item.find("div", {"class": "summary-heading"})
            if heading_div.find("h5").text.strip().lower() == "status":
                status = (
                    item.find("div", {"class": "summary-content"}).text.strip().lower()
                )
                return (
                        status == "completed" or status == "canceled" or status == "dropped"
                )
        else:  # no break/return
            return False

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise MangaNotFound(manga_url=manga_url)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "post-title"})
            title = title_div.find("h1")
            span_found = title.find("span")
            if span_found:
                span_found.decompose()
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img = soup.find("div", {"class": "summary_image"}).find("img")
            return img["data-src"]


class Mangapill(ABCScan):
    rx: re.Pattern = RegExpressions.mangapill_url
    icon_url = "https://mangapill.com/static/favicon/favicon-32x32.png"
    base_url = "https://mangapill.com"
    fmt_url = base_url + "/manga/{manga_id}/{manga_url_name}"
    name = "mangapill"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            summary_container = soup.find("p", {"class": "text-sm"})
            return summary_container.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_container = soup.find("div", {"id": "chapters"}).find_all("a")
            chapters: list[Chapter] = []

            for i, chapter_tag in enumerate(reversed(chapter_container)):
                chapter_url = cls.base_url + chapter_tag["href"]
                chapter_text = chapter_tag.text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(bot, manga_id, manga_url)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")

            for label in soup.find_all("label", {"class": "text-secondary"}):
                if label.text.strip().lower() == "status":
                    status = label.find_next_sibling("div").text.strip().lower()
                    return (
                            status == "finished"
                            or status == "dropped"
                            or status == "canceled"
                            or status == "discontinued"
                    )
            else:
                return False

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title = soup.find("h1", {"class": "font-bold"})
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        _manga_id = await cls.get_manga_id(bot, manga_url)
        if _manga_id != manga_id:
            manga_id = _manga_id
        return cls.fmt_url.format(manga_id=manga_id, manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img = soup.find("div", {"class": "text-transparent"}).find("img")
            return img["data-src"]


class OmegaScans(ABCScan):
    rx: re.Pattern = RegExpressions.omegascans_url
    icon_url = "https://omegascans.org/images/webicon.png"
    base_url = "https://omegascans.org"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "omegascans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @staticmethod
    def _parse_time_string_to_sec(time_string: str) -> float | int:
        return time_string_to_seconds(time_string, ["%m/%d/%Y"])

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis = (
                soup.find("div", {"class": "description-container"})
                .find("p")
                .text.strip()
            )
            return synopsis

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_container = soup.find("ul", {"class": "MuiList-root"}).find_all("a")
            chapters: list[Chapter] = []

            for i, chapter_tag in enumerate(reversed(chapter_container)):
                if (
                        chapter_tag.find("span", {"class": "c-gQxrLF"}) is not None
                ):  # patreon SVG container for chapter
                    break  # if this is found, any further chapters will be patreon only

                chapter_url = cls.base_url + chapter_tag["href"]
                chapter_text = chapter_tag.find("span").text.strip()
                chapters.append(Chapter(chapter_url, chapter_text, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(bot, manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "series-title"})
            title = title_div.find("h1")
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return await super().get_manga_id(
            bot, await cls.fmt_manga_url(bot, "", manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            img = soup.find("img", {"class": "sc-fsQiph"})  # noqa
            return img["src"]

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.post(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            release_dates = soup.find("ul", {"class": "MuiList-root"}).find_all("a")
            date_strings = [
                _date.find("p", {"class": "MuiTypography-root"}).text
                for _date in release_dates
            ]
            if date_strings:
                date_to_check = date_strings[0]
                timestamp = cls._parse_time_string_to_sec(date_to_check)
                if (
                        datetime.now().timestamp() - timestamp
                        > bot.config["constants"]["time-for-manga-to-be-considered-stale"]
                ):
                    return True
            return False


class Bato(ABCScan):
    rx: re.Pattern = RegExpressions.bato_url
    icon_url = "https://bato.to/amsta/img/batoto/favicon.ico"
    base_url = "https://bato.to"
    fmt_url = base_url + "/series/{manga_id}/{manga_url_name}"
    name = "bato.to"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    ).disable()

    @classmethod
    def _make_headers(cls, bot: MangaClient, manga_id: str, manga_url: str):
        url_name = cls.rx.search(manga_url).groupdict().get("url_name", None)
        if not url_name:
            raise MangaNotFound(manga_url)
        headers = super()._make_headers(bot, manga_id, manga_url)
        used_headers = [
            "Accept", "Accept-Encoding", "Accept-Language", "Cache-Control", "Connection", "Host", "Pragma",
            "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site",
            "Sec-Fetch-User", "Upgrade-Insecure-Requests", "User-Agent",
        ]
        updated_headers = {
            "Host": cls.base_url.removeprefix("https://"),
        }
        headers |= updated_headers
        headers = dict_remove_keys(headers, [k for k in headers if k not in used_headers])
        return headers

    @classmethod
    async def check_updates(
            cls, bot: MangaClient, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(bot, manga, _manga_request_url)

    @classmethod
    async def get_synopsis(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            synopsis = soup.find("div", {"class": "limit-html"})
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_all_chapters func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find("div", {"class": "main"})
            # chapter_tags = chapter_list_container.find_all("a")
            chapter_divs = chapter_list_container.find_all("div", {"class": "p-2"})
            chapters: list[Chapter] = []
            for i, chp_tag in enumerate(reversed(chapter_divs)):
                chp_tag = chp_tag.find("a")
                new_chapter_url = chp_tag["href"]
                new_chapter_text = chp_tag.find("b").text.strip()
                chapters.append(
                    Chapter(cls.base_url + new_chapter_url, new_chapter_text, i)
                )
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(bot, manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        container_items = soup.find_all("div", {"class": "attr-item"})
        for item in container_items:
            heading_b = item.find("b", {"class": "text-muted"})
            if heading_b.text.strip().lower() == "upload status:":
                status = item.find("span").text.strip().lower()
                return (
                        status == "completed" or status == "canceled" or status == "dropped"
                )
        else:  # no break/return
            return False

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_human_name func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("h3")
            title = title_div.find("a")
            return title.text.strip()

    @classmethod
    async def get_manga_id(cls, bot: MangaClient, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, bot: MangaClient, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        manga_id = await cls.get_manga_id(bot, manga_url)
        return cls.fmt_url.format(manga_url_name=manga_url_name, manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url, headers=cls._make_headers(bot, manga_id, manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    bot,
                    Exception(
                        "Failed to run get_cover_image func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(manga_url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            cover_image = soup.find(
                "div", {"class": "col-24 col-sm-8 col-md-6 attr-cover"}
            ).find("img")
            image_url = cover_image["src"].strip()
            return image_url


SCANLATORS: dict[str, ABCScan] = {
    VoidScans.name: VoidScans,
    OmegaScans.name: OmegaScans,
    Aquamanga.name: Aquamanga,
    Toonily.name: Toonily,
    TritiniaScans.name: TritiniaScans,
    Manganato.name: Manganato,
    MangaDex.name: MangaDex,
    FlameScans.name: FlameScans,
    Asura.name: Asura,
    ReaperScans.name: ReaperScans,
    AnigliScans.name: AnigliScans,
    Comick.name: Comick,
    LuminousScans.name: LuminousScans,
    LeviatanScans.name: LeviatanScans,
    DrakeScans.name: DrakeScans,
    Mangabaz.name: Mangabaz,
    Mangapill.name: Mangapill,
    Bato.name: Bato,
}
