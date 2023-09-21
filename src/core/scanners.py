from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import curl_cffi.requests
import discord

from ..overwrites import Embed

if TYPE_CHECKING:
    pass

import re

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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

from .errors import MangaNotFoundError, URLAccessFailed
from .objects import ChapterUpdate, Chapter, ABCScan, Manga, PartialManga


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
    def _ensure_ajax_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(manga)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": "page-content-listing item-default", "id": "loop-content"}
            )
            manga_img_tags = manga_container.find_all("img", {"class": "img-responsive"})
            manga_h3s = manga_container.find_all("h3", {"class": "h5"})  # this contains manga a tags
            manga_a_tags = [h3.find("a") for h3 in manga_h3s]
            chapter_containers = manga_container.find_all("div", {"class": "list-chapter"})
            chapter_a_tags = [container.find_all("a") for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag.text.strip()
                cover_url = img_tag["data-src"]
                cover_url = RegExpressions.url_img_size.sub("-193x278", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.post(cls._ensure_ajax_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query), "post_type": "wp-manga"}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"role": "tabpanel", "class": "c-tabs-item"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": ["row", "c-tabs-item__content"]})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        resp = await cls.bot.curl_session.get(cls.base_url.replace("chap", ""))
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_front_page_partial_manga func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        manga_container = soup.find(
            "div", {"class": "panel-content-homepage"}
        )
        manga_img_tags = manga_container.find_all("img", {"class": "img-loading"})
        chapter_containers = manga_container.find_all("div", {"class": "content-homepage-item-right"})
        chapter_a_tags = [container.find_all("a") for container in chapter_containers]
        manga_a_tags = [tags[0] for tags in chapter_a_tags]
        chapter_a_tags = [tags[1:] for tags in chapter_a_tags]

        results: list[PartialManga] = []
        for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
            manga_href = manga_tag["href"]
            manga_title = manga_tag.text.strip()

            cover_url = img_tag["src"]

            chapter_href = [tag["href"] for tag in chapter_tags]
            chapter_text = [tag.text.strip() for tag in chapter_tags]
            if cls.id_first:
                manga_id = await cls.get_manga_id(manga_href)
                manga_url = await cls.fmt_manga_url(manga_id, manga_href)
            else:
                manga_url = await cls.fmt_manga_url("", manga_href)
                manga_id = await cls.get_manga_id(manga_url)
            latest_chapter = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_href, chapter_text))]
            p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                   list(reversed(latest_chapter)), actual_url=manga_href)
            results.append(p_manga)

        return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        text = resp.text

        if "404 - PAGE NOT FOUND" in text:
            raise MangaNotFoundError(manga_url)

        soup = BeautifulSoup(resp.text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        title_div = soup.find("div", {"class": "story-info-right"})
        return title_div.find("h1").text.strip()

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        return cls.fmt_url.format(manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        img = soup.find("span", {"class": "info-image"}).find(
            "img", {"class": "img-loading"}
        )
        return img["src"] if img else None

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        parsed_query = re.sub(r"\W", "_", query)
        search_url = cls.base_url + "/search/story/" + parsed_query
        resp = await cls.bot.curl_session.get(search_url, cache_time=0)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run search func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        # get the first result, manga_url and manga_id (useless)
        results_div = soup.find("div", {"class": "panel-search-story"})  # noqa
        if not results_div:
            return None
        results = results_div.find_all("div", {"class": "search-story-item"})  # noqa
        if len(results) == 0:
            return None

        result_manga_url = results[0].find("a")["href"]

        if cls.id_first:
            manga_id = await cls.get_manga_id(result_manga_url)
            manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
        else:
            manga_url = await cls.fmt_manga_url("", result_manga_url)
            manga_id = await cls.get_manga_id(manga_url)

        manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {cls.name.title()}"

            return (
                Embed(
                    bot=cls.bot,
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


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
    def _make_headers(cls):
        headers = super()._make_headers()
        used_headers = ["User-Agent"]
        return {k: v for k, v in headers.items() if k in used_headers}

    @classmethod
    def _make_cookies(cls) -> curl_cffi.requests.Cookies:
        cookies = curl_cffi.requests.Cookies()
        cookies.set(
            "toonily-mature", "1", "toonily.com", "/",
            int((datetime.now() + timedelta(days=31)).timestamp())
        )
        return cookies

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        resp = await cls.bot.curl_session.get(cls.base_url, headers=cls._make_headers(), cookies=cls._make_cookies())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_front_page_partial_manga func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        manga_divs = soup.find_all("div", {"class": "page-item-detail manga"})
        manga_img_tags = [div.find("img", {"class": "img-responsive"}) for div in manga_divs]
        manga_a_tags = [div.find("a") for div in manga_divs]
        chapter_containers = [div.find("div", {"class": "item-summary"}) for div in manga_divs]
        chapter_a_tags = [container.find_all("a")[1:] for container in chapter_containers]

        results: list[PartialManga] = []
        for manga_tag, chapter_tags, img_tag, in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
            manga_href = manga_tag["href"]
            manga_title = manga_tag["title"].strip()
            cover_url = img_tag["data-src"]
            cover_url = RegExpressions.url_img_size.sub("-224x320", cover_url)

            chapter_href = [tag["href"] for tag in chapter_tags]
            chapter_text = [tag.text.strip() for tag in chapter_tags]
            if cls.id_first:
                manga_id = await cls.get_manga_id(manga_href)
                manga_url = await cls.fmt_manga_url(manga_id, manga_href)
            else:
                manga_url = await cls.fmt_manga_url("", manga_href)
                manga_id = await cls.get_manga_id(manga_url)
            latest_chapter = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_href, chapter_text))]
            p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                   list(reversed(latest_chapter)), actual_url=manga_href)
            results.append(p_manga)

        return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        resp = await cls.bot.curl_session.get(manga_url, headers=cls._make_headers())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")

        synopsis_div = soup.find("div", {"class": "summary__content"})
        replace_tag_with(synopsis_div, "br", "\n")
        synopsis = "\n".join([x.text.strip() for x in synopsis_div.find_all("p")])
        return synopsis

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await cls.bot.curl_session.get(manga_url, headers=cls._make_headers())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        resp = await cls.bot.curl_session.get(manga_url, headers=cls._make_headers())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url, headers=cls._make_headers())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        title_div = soup.find("div", {"class": "post-title"})
        title = title_div.find("h1")
        span_found = title.find("span")
        if span_found:
            span_found.decompose()
        return title.text.strip()

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url, headers=cls._make_headers())
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        cover_image = soup.find("div", {"class": "summary_image"}).find("img")
        image_url = cover_image["data-src"].strip()
        return image_url

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        cookies = cls._make_cookies()
        parsed_query = re.sub(r"\s", "-", query)
        parsed_query = re.sub(r"[^a-zA-Z0-9-]", "", parsed_query)
        search_url = cls.base_url + "/search/" + parsed_query + "?op&author&artist&adult"
        resp = await cls.bot.curl_session.get(search_url, cookies=cookies, headers=cls._make_headers(), cache_time=0)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run search func. Status: "  # TODO: update this for all other search functions
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        # get the first result, manga_url and manga_id (useless)
        results_div = soup.find("div", {"class": "row-eq-height"})  # noqa
        if not results_div:
            return None
        results = results_div.find_all("div", {"class": "page-item-detail manga"})  # noqa
        if len(results) == 0:
            return None

        result_manga_url = results[0].find("a")["href"]
        if cls.id_first:
            manga_id = await cls.get_manga_id(result_manga_url)
            manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
        else:
            manga_url = await cls.fmt_manga_url("", result_manga_url)
            manga_id = await cls.get_manga_id(manga_url)

        manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {cls.name.title()}"

            return (
                Embed(
                    bot=cls.bot,
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


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
    supports_front_page_scraping = False

    # For mangadex, the 'last_known_status' variable is set in the API class @ src/core/mangadexAPI.py

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        return []

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
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        synopsis = await cls.bot.mangadex_api.get_synopsis(manga_id)
        if synopsis:
            return synopsis
        else:
            return "No synopsis found."

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        chapters = await cls.bot.mangadex_api.get_chapters_list(manga_id)
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
            return []

    @classmethod
    async def get_curr_chapter(
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        manga = await cls.bot.mangadex_api.get_manga(manga_id)
        status = manga["data"]["attributes"]["status"].lower()
        return status == "completed" or status == "cancelled"

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await cls.bot.mangadex_api.get_manga(manga_id)
        return manga["data"]["attributes"]["title"]["en"]

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        return super()._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str, manga_url: str
    ) -> str:
        if manga_id is None and manga_url is not None:
            manga_id = await cls.get_manga_id(manga_url)
        return cls.fmt_url.format(manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await cls.bot.mangadex_api.get_manga(manga_id)
        cover_id = [
            x["id"] for x in manga["data"]["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await cls.bot.mangadex_api.get_cover(manga["data"]["id"], cover_id)
        return cover_url

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        results = await cls.bot.mangadex_api.search(title=query, limit=1)
        if not results or not results["data"]:
            return None
        data = results["data"][0]
        manga_id = data["id"]
        manga_obj = await cls.make_manga_object(manga_id, await cls.fmt_manga_url(manga_id, ""))
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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {manga_obj.scanlator.title()}"

            return (
                Embed(
                    bot=cls.bot,
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
    fmt_url = base_url + "/series/{manga_id}-{manga_url_name}"
    name = "flamescans"
    id_first = True
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find("div", {"class": "latest-updates"})
            manga_img_tags = manga_container.find_all("img", {"class": "ts-post-image"})
            chapters_container = manga_container.find_all("div", {"class": "chapter-list"})
            chapter_a_tags = [x.find_all("a") for x in chapters_container]
            manga_a_tags = [x[-1] for x in chapter_a_tags]
            chapter_a_tags = [x[:-1] for x in chapter_a_tags]

            cls._extract_manga_chapter_id(manga_a_tags, chapter_a_tags)

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.find("div", {"class": "epxs"}).text.strip() for tag in chapter_tags]  # noqa

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    def _add_id_to_url(cls, url_to_fix: str) -> str:
        """This will add the appropriate ID to the URL. IDs are fetched every time the update check is ran.
        """

        escaped_base_url = cls.base_url.replace(".", "\\.")
        chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
        manga_pattern = re.compile(rf"{escaped_base_url}/series/\d{{9,}}-", re.MULTILINE)

        if chap_pattern.search(url_to_fix):
            chapter_id = cls.class_kwargs["chapter_id"]
            return chap_pattern.sub(f"{cls.base_url}/{chapter_id}-", url_to_fix)
        elif manga_pattern.search(url_to_fix):
            manga_id = cls.class_kwargs["manga_id"]
            return manga_pattern.sub(f"{cls.base_url}/series/{manga_id}-", url_to_fix)
        return url_to_fix

    @classmethod
    async def load_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        chapter_id, manga_id = cls.class_kwargs.get("chapter_id"), cls.class_kwargs.get("manga_id")
        if not all([chapter_id, manga_id]):
            await cls.get_front_page_partial_manga()  # this func will also set the IDs
        chapter_id, manga_id = cls.class_kwargs["chapter_id"], cls.class_kwargs["manga_id"]
        loaded_mangas = []
        for manga in mangas:
            # noinspection PyProtectedMember
            manga._url = manga._url.format(manga_id=manga_id)
            manga._url = cls._add_id_to_url(manga.url)
            # noinspection PyProtectedMember
            manga._last_chapter.url = manga._last_chapter.url.format(chapter_id=chapter_id)
            # noinspection PyProtectedMember
            manga._last_chapter.url = cls._add_id_to_url(manga.last_chapter.url)
            loaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = chapter.url.format(chapter_id=chapter_id)
                chapter.url = cls._add_id_to_url(chapter.url)
                loaded_chapters.append(chapter)
            loaded_mangas.append(manga)
        return loaded_mangas

    @classmethod
    def unload_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        def remove_id(url: str) -> str:
            escaped_base_url = cls.base_url.replace(".", "\\.")
            chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
            manga_pattern = re.compile(rf"{escaped_base_url}/series/\d{{9,}}-", re.MULTILINE)

            if chap_pattern.search(url):
                return chap_pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            elif manga_pattern.search(url):
                return manga_pattern.sub(f"{cls.base_url}/series/{{manga_id}}-", url)
            else:  # there's no ID in the URL
                if "{manga_id}-" in url or "{chapter_id}-" in url:
                    return url
                if (pattern := re.compile(rf"{escaped_base_url}/series/")).search(url):
                    return pattern.sub(f"{cls.base_url}/series/{{manga_id}}-", url)
                elif (pattern := re.compile(rf"{escaped_base_url}/")).search(url):
                    return pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            return url

        unloaded_manga = []
        for manga in mangas:
            manga = manga.copy()
            manga._url = remove_id(manga.url)
            unloaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = remove_id(chapter.url)
                unloaded_chapters.append(chapter)
            manga._available_chapters = unloaded_chapters
            # noinspection PyProtectedMember
            manga._last_chapter.url = remove_id(manga.last_chapter.url)
            unloaded_manga.append(manga)
        return unloaded_manga

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
                chapter_url = cls._add_id_to_url(chapter_url)

                chapter_title = chapter.find(
                    "span", {"class": "chapternum"}
                ).text.strip()

                chapters.append(Chapter(chapter_url, chapter_title, i))
            return chapters

    @classmethod
    async def get_curr_chapter(
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        _id = cls.class_kwargs.get("manga_id")

        if _id is None:
            await cls.get_front_page_partial_manga()  # this will fetch the manga ID and chapter ID
        _id = cls.class_kwargs["manga_id"]
        return cls.fmt_url.format(manga_id=_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"class": "listupd"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


class Asura(ABCScan):
    rx: re.Pattern = RegExpressions.asura_url
    # base_url = "https://asura.gg"
    base_url = "https://asuracomics.com"  # TODO: temp asura URL
    icon_url = (
        f"{base_url}/wp-content/uploads/2021/03/cropped-Group_1-1-192x192.png"  # noqa
    )
    fmt_url = base_url + "/manga/{manga_id}-{manga_url_name}"
    name = "asura"
    id_first = True  # set to True, so we can get manga ID first before we remove it from the URL.
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.ONE
    )  # 4s interval
    requires_embed_for_chapter_updates = True

    rate_limiter.root.manager.getLimiter(get_url_hostname(base_url))

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    def create_chapter_embed(
            cls, manga: PartialManga | Manga, chapter: Chapter, image_url: str | None = None
    ) -> discord.Embed | None:
        _start_index = manga.cover_url.index(cls.base_url)
        image_url = manga.cover_url[_start_index:]
        return super().create_chapter_embed(manga, chapter, image_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        resp = await cls.bot.curl_session.get(cls.base_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_front_page_partial_manga func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        chapters_container = soup.find_all("div", {"class": "luf"})
        manga_img_tags = [x.parent.find("img", {"class": "ts-post-image"}) for x in chapters_container]
        chapter_a_tags = [x.find_all("a") for x in chapters_container]
        manga_a_tags = [x[0] for x in chapter_a_tags]
        chapter_a_tags = [x[1:] for x in chapter_a_tags]

        cls._extract_manga_chapter_id(manga_a_tags, chapter_a_tags)

        results: list[PartialManga] = []
        for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
            manga_href = manga_tag["href"]
            manga_title = manga_tag["title"].strip()
            cover_url = img_tag["src"]

            chapter_hrefs = [tag["href"] for tag in chapter_tags]
            chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

            if cls.id_first:
                manga_id = await cls.get_manga_id(manga_href)
                manga_url = await cls.fmt_manga_url(manga_id, manga_href)
            else:
                manga_url = await cls.fmt_manga_url("", manga_href)
                manga_id = await cls.get_manga_id(manga_url)
            latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
            p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                   list(reversed(latest_chapters)), actual_url=manga_href)
            results.append(p_manga)
        return results

    @classmethod
    def _add_id_to_url(cls, url_to_fix: str) -> str:
        """This will add the appropriate ID to the URL. IDs are fetched every time the update check is ran.
        """

        escaped_base_url = cls.base_url.replace(".", "\\.")
        chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
        manga_pattern = re.compile(rf"{escaped_base_url}/manga/\d{{9,}}-", re.MULTILINE)

        if chap_pattern.search(url_to_fix):
            chapter_id = cls.class_kwargs["chapter_id"]
            return chap_pattern.sub(f"{cls.base_url}/{chapter_id}-", url_to_fix)
        elif manga_pattern.search(url_to_fix):
            manga_id = cls.class_kwargs["manga_id"]
            return manga_pattern.sub(f"{cls.base_url}/manga/{manga_id}-", url_to_fix)
        return url_to_fix

    @classmethod
    async def load_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        chapter_id, manga_id = cls.class_kwargs.get("chapter_id"), cls.class_kwargs.get("manga_id")
        if not all([chapter_id, manga_id]):
            await cls.get_front_page_partial_manga()  # this func will also set the IDs
        chapter_id, manga_id = cls.class_kwargs["chapter_id"], cls.class_kwargs["manga_id"]
        loaded_mangas = []
        for manga in mangas:
            # noinspection PyProtectedMember
            manga._url = manga._url.format(manga_id=manga_id)
            manga._url = cls._add_id_to_url(manga.url)
            # noinspection PyProtectedMember
            manga._last_chapter.url = manga._last_chapter.url.format(chapter_id=chapter_id)
            # noinspection PyProtectedMember
            manga._last_chapter.url = cls._add_id_to_url(manga.last_chapter.url)
            loaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = chapter.url.format(chapter_id=chapter_id)
                chapter.url = cls._add_id_to_url(chapter.url)
                loaded_chapters.append(chapter)
            loaded_mangas.append(manga)
        return loaded_mangas

    @classmethod
    def unload_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        def remove_id(url: str) -> str:
            escaped_base_url = cls.base_url.replace(".", "\\.")
            chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
            manga_pattern = re.compile(rf"{escaped_base_url}/manga/\d{{9,}}-", re.MULTILINE)

            if chap_pattern.search(url):
                return chap_pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            elif manga_pattern.search(url):
                return manga_pattern.sub(f"{cls.base_url}/manga/{{manga_id}}-", url)
            else:  # there's no ID in the URL
                if "{manga_id}-" in url or "{chapter_id}-" in url:
                    return url
                if (pattern := re.compile(rf"{escaped_base_url}/manga/")).search(url):
                    return pattern.sub(f"{cls.base_url}/manga/{{manga_id}}-", url)
                elif (pattern := re.compile(rf"{escaped_base_url}/")).search(url):
                    return pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            return url

        unloaded_manga = []
        for manga in mangas:
            manga = manga.copy()
            manga._url = remove_id(manga.url)
            unloaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = remove_id(chapter.url)
                unloaded_chapters.append(chapter)
            manga._available_chapters = unloaded_chapters
            # noinspection PyProtectedMember
            manga._last_chapter.url = remove_id(manga.last_chapter.url)
            unloaded_manga.append(manga)
        return unloaded_manga

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        synopsis = soup.find(
            "div", {"class": "entry-content", "itemprop": "description"}
        )
        return synopsis.text.strip().replace("&nbsp;", "")

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "eplister"})
        chapters_list = chapter_list_container.find_all("a")
        chapters: list[Chapter] = []
        for i, chapter in enumerate(reversed(chapters_list)):
            chapter_url = chapter["href"]
            chapter_url = cls._add_id_to_url(chapter_url)
            chapter_text = chapter.find("span", {"class": "chapternum"}).text.strip()
            chapters.append(Chapter(chapter_url, chapter_text, i))
        return chapters

    @classmethod
    async def get_curr_chapter(
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1", {"class": "entry-title"})
        return title_tag.text.strip()

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        _id = cls.class_kwargs.get("manga_id")

        if _id is None:
            await cls.get_front_page_partial_manga()  # this will fetch the manga ID and chapter ID
        _id = cls.class_kwargs["manga_id"]
        return cls.fmt_url.format(manga_id=_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        cover_image = soup.find("div", {"class": "thumb", "itemprop": "image"}).find(
            "img"
        )
        if cover_image:
            img_url = cover_image["src"]
            _start_index = img_url.index(cls.base_url)
            img_url = img_url[_start_index:]
            return img_url

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        resp = await cls.bot.curl_session.get(cls.base_url, params=params, cache_time=0)  # no caching
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run search func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        # get the first result, manga_url and manga_id (useless)
        results_div = soup.find("div", {"class": "listupd"})  # noqa
        if not results_div:
            return None
        results = results_div.find_all("div", {"class": "bsx"})  # noqa
        if len(results) == 0:
            return None

        result_manga_url = results[0].find("a")["href"]
        manga_id = await cls.get_manga_id(result_manga_url)
        manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)

        manga_obj = await cls.make_manga_object(manga_id, manga_url)
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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {cls.name.title()}"

            return (
                Embed(
                    bot=cls.bot,
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


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
    requires_embed_for_chapter_updates = True

    @classmethod
    def _make_headers(cls):
        headers = super()._make_headers()
        used_headers = [
            ":Authority", ":Method", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Pragma", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest",
            "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", "Upgrade-Insecure-Requests", "User-Agent",
        ]
        headers = dict_remove_keys(headers, [k for k in headers if k not in used_headers])
        return headers

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    def create_chapter_embed(
            cls, manga: PartialManga | Manga, chapter: Chapter, image_url: str | None = None
    ) -> discord.Embed | None:
        image_url = Constants.no_img_available_url
        return super().create_chapter_embed(manga, chapter, image_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": "page-content-listing item-big_thumbnail", "id": "loop-content"}
            )
            manga_img_tags = manga_container.find_all("img", {"class": "img-responsive"})
            manga_h3s = manga_container.find_all("h3", {"class": "h5"})  # this contains manga a tags
            manga_a_tags = [h3.find("a") for h3 in manga_h3s]
            chapter_containers = manga_container.find_all("div", {"class": "list-chapter"})
            chapter_a_tags = [container.find_all("a", {"class": "btn-link"}) for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag.text.strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("-193x278", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query), "post_type": "wp-manga", "op": "", "author": "", "artist": "", "release": "",
                  "adult": ""}
        async with cls.bot.session.get(cls.base_url, params=params, headers=cls._make_headers(), cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"role": "tabpanel", "class": "c-tabs-item"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": ["row", "c-tabs-item__content"]})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
    requires_embed_for_chapter_updates = True

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    def create_chapter_embed(
            cls, manga: PartialManga | Manga, chapter: Chapter, image_url: str | None = None
    ) -> discord.Embed | None:
        image_url = Constants.no_img_available_url
        return super().create_chapter_embed(manga, chapter, image_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        resp = await cls.bot.curl_session.get(cls.base_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_front_page_partial_manga func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        manga_container = soup.find("div", {"class": "grid grid-cols-1 gap-4 lg:grid-cols-4"})
        manga_img_tags = manga_container.find_all("img", {"class": "h-32 w-20 rounded lg:h-36 lg:w-24"})
        chapters_container = manga_container.find_all("div", {"class": "focus:outline-none"})
        chapter_a_tags = [x.find_all("a") for x in chapters_container]
        manga_a_tags = [x[0] for x in chapter_a_tags]
        chapter_a_tags = [x[1:] for x in chapter_a_tags]
        chapter_p_tags = [y.find("p") for x in chapter_a_tags for y in x]
        for p_tag in chapter_p_tags:
            p_tag.decompose()

        results: list[PartialManga] = []
        for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
            manga_href = manga_tag["href"]
            manga_title = manga_tag.text.strip()
            cover_url = img_tag["src"]

            chapter_hrefs = [tag["href"] for tag in chapter_tags]
            chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

            if cls.id_first:
                manga_id = await cls.get_manga_id(manga_href)
                manga_url = await cls.fmt_manga_url(manga_id, manga_href)
            else:
                manga_url = await cls.fmt_manga_url("", manga_href)
                manga_id = await cls.get_manga_id(manga_url)
            latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
            p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                   list(reversed(latest_chapters)), actual_url=manga_href)
            results.append(p_manga)

        return results

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
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_url: str, *, page: int | None = None
    ) -> tuple[list[Chapter] | None, int]:
        """
        Returns a tuple of (list of chapters [descending order], max number of chapters there are)
        for the given manga page.

        Args:
     - the bot instance
            manga_url: str - the manga url
            page: int | None - the page number to get chapters from. If None, get all chapters

        Returns:
            tuple[list[Chapter] | None, int] - the list of chapters and max number of chapters there are
        """
        if (
                page is not None and page > 1
        ):  # by default, no param = page 1, so we only consider page 2+
            resp = await cls.bot.curl_session.get(manga_url.rstrip("/") + f"?page={page}")
        else:
            resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()

        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})

        chapters_container_parent = chapter_list_container.find_parent(
            "div",
            {
                "class": "focus:outline-none max-w-6xl bg-white dark:bg-neutral-850 rounded mt-6"
            },
        )
        if chapters_container_parent is None:
            cls.bot.logger.warning(
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
            cls, manga_id: str, manga_url: str, *, page: int | None = None
    ) -> list[Chapter] | None:
        if page is not None and page == 0:
            return (await cls.get_chapters_on_page(manga_url, page=page))[0]
        else:
            max_chapters = float("inf")
            chapters: list[Chapter] = []
            while len(chapters) < max_chapters:
                await asyncio.sleep(1)  # add some delay to reduce rate-limits
                next_page_chapters, max_chapters = await cls.get_chapters_on_page(
                    manga_url, page=page
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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1")
        return title_tag.text.strip()

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str, manga_url: str
    ) -> str:
        if manga_id is None and manga_url is not None:
            manga_id = await cls.get_manga_id(manga_url)
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_id=manga_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            raise URLAccessFailed(resp.request.url, resp.status_code)
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")
        cover_div = soup.find("div", {"class": "transition"})
        cover_image = cover_div.find("img")
        return cover_image["src"] if cover_image else None


class AnigliScans(ABCScan):
    rx: re.Pattern = RegExpressions.anigliscans_url
    icon_url = "https://anigliscans.xyz/wp-content/uploads/2022/07/cropped-Untitled671_20220216124756-192x192.png"
    base_url = "https://anigliscans.xyz"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "anigliscans"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @classmethod
    def _make_headers(cls):
        headers = super()._make_headers()
        used_headers = [
            ":Authority", ":Method", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Pragma", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest",
            "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", "Upgrade-Insecure-Requests", "User-Agent",
        ]
        headers = dict_remove_keys(headers, [k for k in headers if k not in used_headers])
        return headers

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapters_container = soup.find_all("div", {"class": "luf"})
            manga_img_tags = [x.parent.find("img", {"class": "ts-post-image"}) for x in chapters_container]
            chapter_a_tags = [x.find_all("a") for x in chapters_container]
            manga_a_tags = [x[0] for x in chapter_a_tags]
            chapter_a_tags = [x[1:] for x in chapter_a_tags]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with cls.bot.session.get(cls.base_url, params=params, headers=cls._make_headers(), cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            manga_id = await cls.get_manga_id(result_manga_url)
            manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
    supports_front_page_scraping = False

    # For comick, the 'last_known_status' variable is set in the Comick api @ src/core/comickAPI.py

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        return []

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        return await cls.bot.comick_api.get_synopsis(manga_id)

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        chapters = await cls.bot.comick_api.get_chapters_list(manga_id)
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
            return []

    @classmethod
    async def get_curr_chapter(
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
        if chapters:
            return chapters[-1]
        return None

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await cls.bot.comick_api.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return None
        return manga["comic"]["title"]

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        manga = await cls.bot.comick_api.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return False
        return manga["comic"]["status"] == 2

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        return await cls.bot.comick_api.get_cover(manga_id)

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        result: list[dict] = await cls.bot.comick_api.search(query, limit=1)  # noqa
        if not result: return None  # noqa
        manga_obj = await cls.make_manga_object(

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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {cls.name.title()}"

            return (
                Embed(
                    bot=cls.bot,
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
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        resp = await cls.bot.curl_session.get(cls.base_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(
                Exception(
                    "Failed to run get_front_page_partial_manga func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        chapters_container = soup.find_all("div", {"class": "luf"})
        manga_img_tags = [x.parent.find("img", {"class": "ts-post-image"}) for x in chapters_container]

        chapter_a_tags = [x.find_all("a") for x in chapters_container]
        manga_a_tags = [x[0] for x in chapter_a_tags]
        chapter_a_tags = [x[1:] for x in chapter_a_tags]

        results: list[PartialManga] = []
        for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
            manga_href = manga_tag["href"]
            manga_title = manga_tag["title"].strip()
            cover_url = img_tag["src"]

            chapter_hrefs = [tag["href"] for tag in chapter_tags]
            chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

            if cls.id_first:
                manga_id = await cls.get_manga_id(manga_href)
                manga_url = await cls.fmt_manga_url(manga_id, manga_href)
            else:
                manga_url = await cls.fmt_manga_url("", manga_href)
                manga_id = await cls.get_manga_id(manga_url)
            latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
            p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                   list(reversed(latest_chapters)), actual_url=manga_href)
            results.append(p_manga)

        return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_synopsis func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_all_chapters func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_human_name func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.find("h1", {"class": "entry-title"}).text

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str | None:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run is_series_completed func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        status_div = soup.find("div", {"class": "imptdt"})  # noqa
        status = status_div.find("i").text.strip().lower()
        return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        resp = await cls.bot.curl_session.get(manga_url)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run get_cover_image func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        img_div = soup.find("div", {"class": "thumb"})
        return img_div.find("img")["src"]

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        resp = await cls.bot.curl_session.get(cls.base_url, params=params, cache_time=0)
        cls.last_known_status = resp.status_code, datetime.now().timestamp()
        if resp.status_code != 200:
            await cls.report_error(

                Exception(
                    "Failed to run search func. Status: "
                    + str(resp.status_code)
                    + " Request URL: "
                    + str(resp.url)
                ),
                file=write_to_discord_file(cls.name + ".html", resp.text),
            )
            raise URLAccessFailed(resp.request.url, resp.status_code)

        soup = BeautifulSoup(resp.text, "html.parser")
        # get the first result, manga_url and manga_id (useless)
        results_div = soup.find("div", {"class": "listupd"})  # noqa
        if not results_div:
            return None
        results = results_div.find_all("div", {"class": "bsx"})  # noqa
        if len(results) == 0:
            return None

        result_manga_url = results[0].find("a")["href"]
        manga_id = await cls.get_manga_id(result_manga_url)
        manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)

        manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
            desc += f"**First Chapter:** {first_chapter}\n"
            desc += f"**Scanlator:** {cls.name.title()}"

            return (
                Embed(
                    bot=cls.bot,
                    title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                    description=desc
                )
                .add_field(name="Synopsis", value=synopsis_text, inline=False)
                .set_image(url=manga_obj.cover_url)
            )


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

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")

            manga_divs = soup.select("div.postbody > div.bixbox:first-child > div.listupd > div.utao")
            if not manga_divs:
                return []
            manga_img_tags = [x.select_one("div.imgu > a > img.ts-post-image") for x in manga_divs]
            manga_a_tags = [x.select_one("div.luf > a") for x in manga_divs]
            chapter_a_tags = [x.select("div.luf > ul > li > a") for x in manga_divs]

            cls._extract_manga_chapter_id(manga_a_tags, list(chapter_a_tags))

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    def _add_id_to_url(cls, url_to_fix: str) -> str:
        """This will add the appropriate ID to the URL. IDs are fetched every time the update check is ran.
        """

        escaped_base_url = cls.base_url.replace(".", "\\.")
        chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
        manga_pattern = re.compile(rf"{escaped_base_url}/series/\d{{9,}}-", re.MULTILINE)

        if chap_pattern.search(url_to_fix):
            chapter_id = cls.class_kwargs["chapter_id"]
            return chap_pattern.sub(f"{cls.base_url}/{chapter_id}-", url_to_fix)
        elif manga_pattern.search(url_to_fix):
            manga_id = cls.class_kwargs["manga_id"]
            return manga_pattern.sub(f"{cls.base_url}/series/{manga_id}-", url_to_fix)
        return url_to_fix

    @classmethod
    async def load_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        chapter_id, manga_id = cls.class_kwargs.get("chapter_id"), cls.class_kwargs.get("manga_id")
        if not all([chapter_id, manga_id]):
            await cls.get_front_page_partial_manga()  # this func will also set the IDs
        chapter_id, manga_id = cls.class_kwargs["chapter_id"], cls.class_kwargs["manga_id"]
        loaded_mangas = []
        for manga in mangas:
            # noinspection PyProtectedMember
            manga._url = manga._url.format(manga_id=manga_id)
            manga._url = cls._add_id_to_url(manga.url)
            # noinspection PyProtectedMember
            manga._last_chapter.url = manga._last_chapter.url.format(chapter_id=chapter_id)
            # noinspection PyProtectedMember
            manga._last_chapter.url = cls._add_id_to_url(manga.last_chapter.url)
            loaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = chapter.url.format(chapter_id=chapter_id)
                chapter.url = cls._add_id_to_url(chapter.url)
                loaded_chapters.append(chapter)
            loaded_mangas.append(manga)
        return loaded_mangas

    @classmethod
    def unload_manga_objects(cls, mangas: list[Manga]) -> list[Manga]:
        def remove_id(url: str) -> str:
            escaped_base_url = cls.base_url.replace(".", "\\.")
            chap_pattern = re.compile(rf"{escaped_base_url}/\d{{9,}}-", re.MULTILINE)
            manga_pattern = re.compile(rf"{escaped_base_url}/series/\d{{9,}}-", re.MULTILINE)

            if chap_pattern.search(url):
                return chap_pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            elif manga_pattern.search(url):
                return manga_pattern.sub(f"{cls.base_url}/series/{{manga_id}}-", url)
            else:  # there's no ID in the URL
                if "{manga_id}-" in url or "{chapter_id}-" in url:
                    return url
                if (pattern := re.compile(rf"{escaped_base_url}/manga/")).search(url):
                    return pattern.sub(f"{cls.base_url}/series/{{manga_id}}-", url)
                elif (pattern := re.compile(rf"{escaped_base_url}/")).search(url):
                    return pattern.sub(f"{cls.base_url}/{{chapter_id}}-", url)
            return url

        unloaded_manga = []
        for manga in mangas:
            manga = manga.copy()
            manga._url = remove_id(manga.url)
            unloaded_chapters = []
            for chapter in manga.available_chapters:
                chapter.url = remove_id(chapter.url)
                unloaded_chapters.append(chapter)
            manga._available_chapters = unloaded_chapters
            # noinspection PyProtectedMember
            manga._last_chapter.url = remove_id(manga.last_chapter.url)
            unloaded_manga.append(manga)
        return unloaded_manga

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                if resp.status == 404:
                    raise MangaNotFoundError(manga_url)
                await cls.report_error(

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
            synopsis = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                if resp.status == 404:
                    raise MangaNotFoundError(manga_url)
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                if resp.status == 404:
                    raise MangaNotFoundError(manga_url)
                await cls.report_error(

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
            return soup.find("h1", {"class": "entry-title"}).text

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str | None:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                if resp.status == 404:
                    raise MangaNotFoundError(manga_url)
                await cls.report_error(

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
            status_div = soup.find("div", {"class": "imptdt"})  # noqa
            status = status_div.find("i").text.strip().lower()
            return status == "completed" or status == "dropped" or status == "canceled"

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        _id = cls.class_kwargs.get("manga_id")

        if _id is None:
            await cls.get_front_page_partial_manga()  # this will fetch the manga ID and chapter ID
        _id = cls.class_kwargs["manga_id"]
        return cls.fmt_url.format(manga_id=_id, manga_url_name=manga_url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                if resp.status == 404:
                    raise MangaNotFoundError(manga_url)
                await cls.report_error(

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
            img_div = soup.find("div", {"class": "thumb"})
            return img_div.find("img")["src"]

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            manga_id = await cls.get_manga_id(result_manga_url)
            manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


class LSComic(ABCScan):
    rx: re.Pattern = RegExpressions.lscomic_url
    icon_url = "https://lscomic.com/wp-content/uploads/2023/09/cropped-isotipo-c-192x192.png"
    base_url = "https://lscomic.com"
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "lscomic"
    id_first = False
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=20, period=Minutes.ONE
    )  # 3s interval

    @staticmethod
    def _ensure_ajax_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run get_synopsis func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_divs = soup.find_all("div", {"class": "page-item-detail manga"})
            manga_img_tags = [div.find("img", {"class": "img-responsive"}) for div in manga_divs]
            manga_a_tags = [div.find("a") for div in manga_divs]
            chapter_containers = [div.find("div", {"class": "item-summary"}) for div in manga_divs]
            chapter_a_tags = [container.find_all("a")[1:] for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag, in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["data-src"]
                cover_url = RegExpressions.url_img_size.sub("-224x320", cover_url)

                chapter_href = [tag["href"] for tag in chapter_tags]
                chapter_text = [tag.text.strip() for tag in chapter_tags]
                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapter = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_href, chapter_text))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapter)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.post(cls._ensure_ajax_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str | None:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.post(cls._ensure_ajax_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
                        > cls.bot.config["constants"]["time-for-manga-to-be-considered-stale"]
                ):
                    return True
            return False

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            return img_div.find("img")["data-src"].strip()


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
    def _make_headers(cls):
        headers = super()._make_headers()
        used_header_keys = [
            ":Authority", ":Method", ":Scheme", "Accept", "Accept-Encoding", "Accept-Language",
            "Cache-Control", "Content-Length", "Origin", "Pragma", "Sec-Ch-Ua", "Sec-Ch-Ua-Mobile",
            "Sec-Ch-Ua-Platform", "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User",
            "Upgrade-Insecure-Requests", "User-Agent" "X-Requested-With"
        ]
        updated_headers = {
            "Origin": cls.base_url,
        }
        to_ajax_endpoint = is_from_stack_origin(class_name=cls.__name__, function_name="get_all_chapters")
        # if from ajax endpoint
        if to_ajax_endpoint:
            updated_headers |= {
                ":Method": "POST", "Accept": "*/*", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
            }
            used_header_keys = list(set(used_header_keys) - {"Sec-Fetch-User", "Upgrade-Insecure-Requests"})
        else:  # normal endpoint
            used_header_keys = list(set(used_header_keys) - {"Content-Length", "Origin", "Referer", "X-Requested-With"})
        updated_headers = {key: value for key, value in updated_headers.items() if key in used_header_keys}
        headers.update(updated_headers)
        headers = dict_remove_keys(headers, [key for key in headers if key not in used_header_keys])
        return headers

    @staticmethod
    def _ensure_ajax_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(manga)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": "page-content-listing item-big_thumbnail", "id": "loop-content"}
            )
            manga_h3s = manga_container.find_all("h3", {"class": "h5"})  # this contains manga a tags
            manga_a_tags = [h3.find("a") for h3 in manga_h3s]
            chapter_containers = manga_container.find_all("div", {"class": "list-chapter"})
            manga_img_tags = [x.parent.parent.find("img", {"class": "img-responsive"}) for x in chapter_containers]
            chapter_a_tags = [container.find_all("a", {"class": "btn-link"}) for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag.text.strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("-193x278", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.post(
                cls._ensure_ajax_url(manga_url), headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise MangaNotFoundError(manga_url=manga_url)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                return await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                return await cls.report_error(

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
            return img["data-src"]


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
    def _ensure_ajax_url(url: str) -> str:
        if url.endswith("/"):
            url = url[:-1]
        if "/ajax/chapters/" not in url:
            return url + "/ajax/chapters/"
        else:
            return url + "/"

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate | None:
        return await super().check_updates(manga)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": "page-content-listing item-big_thumbnail", "id": "loop-content"}
            )
            manga_img_tags = manga_container.find_all("img", {"class": "img-responsive"})
            manga_h3s = manga_container.find_all("h3", {"class": "h5"})  # this contains manga a tags
            manga_a_tags = [h3.find("a") for h3 in manga_h3s]
            chapter_containers = manga_container.find_all("div", {"class": "list-chapter"})
            chapter_a_tags = [container.find_all("a", {"class": "btn-link"}) for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag.text.strip()
                cover_url = img_tag["data-src"]
                cover_url = RegExpressions.url_img_size.sub("-193x278", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(cls._ensure_ajax_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.post(cls._ensure_ajax_url(manga_url)) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run is_series_completed func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise MangaNotFoundError(manga_url=manga_url)

            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query), "post_type": "wp-manga"}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"role": "tabpanel", "class": "c-tabs-item"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": ["row", "c-tabs-item__content"]})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
    requires_embed_for_chapter_updates = True

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    def create_chapter_embed(
            cls, manga: PartialManga | Manga, chapter: Chapter, image_url: str | None = None
    ) -> discord.Embed | None:
        image_url = Constants.no_img_available_url
        return super().create_chapter_embed(manga, chapter, image_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url + "/chapters") as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": "grid"}
            )
            manga_img_tags = manga_container.find_all("img", {"class": "text-transparent"})
            chapter_containers = manga_container.find_all("div", {"class": "px-1"})
            chapter_a_tags = [container.find_all("a") for container in chapter_containers]
            manga_a_tags = [tag[-1] for tag in chapter_a_tags]
            chapter_a_tags = [tag[:-1] for tag in chapter_a_tags]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = cls.base_url + manga_tag["href"]
                manga_title = manga_tag.find("div").text.strip()
                cover_url = img_tag["data-src"]

                chapter_hrefs = [cls.base_url + tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip().replace("#", "Chapter ") for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_url)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        _manga_id = await cls.get_manga_id(manga_url)
        if _manga_id != manga_id:
            manga_id = _manga_id
        return cls.fmt_url.format(manga_id=manga_id, manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"q": url_encode(query), "type": "", "status": ""}
        search_url = cls.base_url + "/search"
        async with cls.bot.session.get(search_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {
                "class": "my-3 grid justify-end gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-5"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div")  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            result_manga_url = cls.base_url + result_manga_url
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                return []

            soup = BeautifulSoup(await resp.text(), "html.parser")
            manga_container = soup.find(
                "div", {"class": ["grid-cols-2"]}
            )
            manga_img_tags = manga_container.find_all("img", {"class": "c-eluAox"})
            manga_h5s = manga_container.find_all("h5", {"class": "c-dZWYAw"})
            manga_a_tags = [h5.parent for h5 in manga_h5s]
            chapter_containers = manga_container.find_all("div", {"class": "c-ibOvzC"})
            chapter_a_tags = [container.find_all("a") for container in chapter_containers]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = cls.base_url + manga_tag["href"]
                manga_title = manga_tag.text.strip()
                cover_url = img_tag["src"]

                chapter_hrefs = [cls.base_url + tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.find("div", {"class": "c-cSMWqC"}).text.strip() for tag in chapter_tags]

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_url)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    async def get_human_name(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url("", manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.post(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
                        > cls.bot.config["constants"]["time-for-manga-to-be-considered-stale"]
                ):
                    return True
            return False

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"term": query}
        search_url = "https://api." + cls.base_url.removeprefix("https://") + "/series/search"
        async with cls.bot.session.post(search_url, json=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            results = await resp.json()
            if len(results) == 0:
                return None

            result_manga_url = cls.fmt_url.format(manga_url_name=results[0]["series_slug"])
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
    supports_front_page_scraping = False

    @classmethod
    def _make_headers(cls):
        headers = super()._make_headers()
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
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        return []

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            if not synopsis:
                return "No synopsis found."
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        chapters: list[Chapter] = await cls.get_all_chapters(manga_id, manga_url)
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
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
    async def get_manga_id(cls, manga_url: str) -> str:
        return cls.rx.search(manga_url).groupdict()["id"]

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        manga_url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        manga_id = await cls.get_manga_id(manga_url)
        return cls.fmt_url.format(manga_url_name=manga_url_name, manga_id=manga_id)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"word": url_encode(query)}
        search_url = cls.base_url + "/search"
        async with cls.bot.session.get(search_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"id": "series-list"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", )  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            result_manga_url = cls.base_url + result_manga_url
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)
            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


class NightScans(ABCScan):
    icon_url = "https://nightscans.net/wp-content/uploads/2023/03/cropped-PicsArt_09-07-01.23.08-1-2.png"
    base_url = "https://nightscans.net"
    fmt_url = base_url + "/series/{manga_url_name}"
    name = "nightscans"
    id_first = False
    rx: re.Pattern = RegExpressions.nightscans_url
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.FIVE
    )  # 20s interval

    @classmethod
    def _make_headers(cls):
        headers = super()._make_headers()
        # used_headers = ["User-Agent"]
        used_headers = {}
        return {k: v for k, v in headers.items() if k in used_headers}

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            manga_container = soup.find_all("div", {"class": "listupd"})[1]  # noqa
            manga_img_tags = manga_container.find_all("img", {"class": "ts-post-image"})[::2]
            chapters_container = manga_container.find_all("div", {"class": "bigor"})  # noqa
            manga_a_tags = [x.find("a") for x in chapters_container]
            chapter_a_tags = [x.find_all("a", {"class": "maincl"}) for x in chapters_container]  # noqa

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["data-lazy-src"]

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            synopsis = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div = soup.find("div", {"class": "imptdt"})  # noqa
        status = status_div.find("i").text.strip()
        return status.lower() == "completed" or status.lower() == "dropped"

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            return soup.find("h1", {"class": "entry-title"}).text.strip()

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url, headers=cls._make_headers()) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            img_div = soup.find("div", {"class": "thumb", "itemprop": "image"})
            return img_div.find("img")["data-lazy-src"]

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"class": "listupd"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


class SuryaScans(ABCScan):
    icon_url = "https://suryascans.com/wp-content/uploads/2022/09/cropped-surya-logo1x-192x192.png"
    base_url = "https://suryascans.com"
    fmt_url = base_url + "/manga/{manga_url_name}"
    name = "suryascans"  # noqa
    id_first = False
    rx: re.Pattern = RegExpressions.suryascans_url
    rate_limiter.root.manager.getLimiter(
        get_url_hostname(base_url), calls=15, period=Minutes.FIVE
    )  # 20s interval

    @classmethod
    async def check_updates(
            cls, manga: Manga, _manga_request_url: str | None = None
    ) -> ChapterUpdate:
        return await super().check_updates(manga, _manga_request_url)

    @classmethod
    async def get_front_page_partial_manga(cls) -> list[PartialManga]:
        async with cls.bot.session.get(cls.base_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(
                    Exception(
                        "Failed to run get_front_page_partial_manga func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            chapters_container = soup.find_all("div", {"class": "luf"})
            manga_img_tags = [x.parent.find("img", {"class": "ts-post-image"}) for x in chapters_container]
            chapter_a_tags = [x.find_all("a") for x in chapters_container]
            manga_a_tags = [x[0] for x in chapter_a_tags]
            chapter_a_tags = [x[1:] for x in chapter_a_tags]

            results: list[PartialManga] = []
            for manga_tag, chapter_tags, img_tag in zip(manga_a_tags, chapter_a_tags, manga_img_tags):
                manga_href = manga_tag["href"]
                manga_title = manga_tag["title"].strip()
                cover_url = img_tag["src"]
                cover_url = RegExpressions.url_img_size.sub("", cover_url)

                chapter_hrefs = [tag["href"] for tag in chapter_tags]
                chapter_texts = [tag.text.strip() for tag in chapter_tags]  # noqa

                if cls.id_first:
                    manga_id = await cls.get_manga_id(manga_href)
                    manga_url = await cls.fmt_manga_url(manga_id, manga_href)
                else:
                    manga_url = await cls.fmt_manga_url("", manga_href)
                    manga_id = await cls.get_manga_id(manga_url)
                latest_chapters = [Chapter(x, y, i) for i, (x, y) in enumerate(zip(chapter_hrefs, chapter_texts))]
                p_manga = PartialManga(manga_id, manga_title, manga_url, cls.name, cover_url,
                                       list(reversed(latest_chapters)), actual_url=manga_href)
                results.append(p_manga)

            return results

    @classmethod
    async def get_synopsis(cls, manga_id: str, manga_url: str) -> str:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            synopsis = soup.find(
                "div", {"class": "entry-content", "itemprop": "description"}
            )
            return synopsis.text.strip()

    @classmethod
    async def get_all_chapters(
            cls, manga_id: str, manga_url: str
    ) -> list[Chapter] | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> Chapter | None:
        return await super().get_curr_chapter(manga_id, manga_url)

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div = soup.find("div", {"class": "imptdt"})  # noqa
        status = status_div.find("i").text.strip()
        return status.lower() == "completed" or status.lower() == "dropped"

    @classmethod
    async def is_series_completed(
            cls, manga_id: str, manga_url: str
    ) -> bool:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            return soup.find("h1", {"class": "entry-title"}).text.strip()

    @classmethod
    async def get_manga_id(cls, manga_url: str) -> str:
        return await super().get_manga_id(
            await cls.fmt_manga_url(None, manga_url)
        )

    @classmethod
    async def fmt_manga_url(
            cls, manga_id: str | None, manga_url: str
    ) -> str:
        url_name = cls.rx.search(manga_url).groupdict()["url_name"]
        return cls.fmt_url.format(manga_url_name=url_name)

    @classmethod
    async def get_cover_image(
            cls, manga_id: str, manga_url: str
    ) -> str | None:
        async with cls.bot.session.get(manga_url) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

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
            img_div = soup.find("div", {"class": "thumb", "itemprop": "image"})
            return img_div.find("img")["src"]

    @classmethod
    async def search(
            cls, query: str, as_em: bool = True
    ) -> discord.Embed | Manga | None:
        params = {"s": url_encode(query)}
        async with cls.bot.session.get(cls.base_url, params=params, cache_time=0) as resp:
            cls.last_known_status = resp.status, datetime.now().timestamp()
            if resp.status != 200:
                await cls.report_error(

                    Exception(
                        "Failed to run search func. Status: "
                        + str(resp.status)
                        + " Request URL: "
                        + str(resp.url)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text()),
                )
                raise URLAccessFailed(resp.request_info.url, resp.status)
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # get the first result, manga_url and manga_id (useless)
            results_div = soup.find("div", {"class": "listupd"})  # noqa
            if not results_div:
                return None
            results = results_div.find_all("div", {"class": "bsx"})  # noqa
            if len(results) == 0:
                return None

            result_manga_url = results[0].find("a")["href"]
            if cls.id_first:
                manga_id = await cls.get_manga_id(result_manga_url)
                manga_url = await cls.fmt_manga_url(manga_id, result_manga_url)
            else:
                manga_url = await cls.fmt_manga_url("", result_manga_url)
                manga_id = await cls.get_manga_id(manga_url)

            manga_obj = await cls.make_manga_object(manga_id, manga_url)

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
                desc += f"**First Chapter:** {first_chapter}\n"
                desc += f"**Scanlator:** {cls.name.title()}"

                return (
                    Embed(
                        bot=cls.bot,
                        title=manga_obj.human_name, url=manga_obj.url, color=discord.Color.green(),
                        description=desc
                    )
                    .add_field(name="Synopsis", value=synopsis_text, inline=False)
                    .set_image(url=manga_obj.cover_url)
                )


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
    LSComic.name: LSComic,
    DrakeScans.name: DrakeScans,
    Mangabaz.name: Mangabaz,
    Mangapill.name: Mangapill,
    Bato.name: Bato,
    NightScans.name: NightScans,
    SuryaScans.name: SuryaScans,
}
