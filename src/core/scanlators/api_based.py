import hashlib
import re
from types import SimpleNamespace
from typing import Optional

import discord

from src.core.objects import Chapter, PartialManga
from .classes import AbstractScanlator, scanlators
from ...static import RegExpressions
from ...utils import raise_and_report_for_status

__all__ = (
    "scanlators",
)


class _Comick(AbstractScanlator):
    rx: re.Pattern = RegExpressions.comick_url
    icon_url = "https://comick.cc/static/icons/unicorn-256_maskable.png"
    base_url = "https://comick.cc"
    fmt_url = base_url + "/comic/{url_name}?lang=en"
    chp_url_fmt = base_url + "/comic/{url_name}/{chapter_id}"

    def __init__(self, name: str):
        super().__init__(name)
        self.name: str = name

    @property
    def json_tree(self):
        return SimpleNamespace(
            properties=SimpleNamespace(
                icon_url=self.icon_url,
                base_url=self.base_url,
                requires_update_embed=False,
                can_render_cover=True,
                format_urls=SimpleNamespace(
                    manga=self.fmt_url.removesuffix("?lang=en"),
                )
            )
        )

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        return []

    def check_ownership(self, raw_url: str) -> bool:
        return self.rx.search(raw_url) is not None

    async def get_synopsis(self, raw_url: str) -> str:
        manga_id = await self.get_id(raw_url)
        return await self.bot.apis.comick.get_synopsis(manga_id)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        manga_id = await self.get_id(raw_url)
        chapters = await self.bot.apis.comick.get_chapters_list(manga_id)
        if chapters:
            url_name = self.rx.search(raw_url).groupdict()["url_name"]
            return [
                Chapter(
                    self.chp_url_fmt.format(
                        url_name=url_name, chapter_id=chp["hid"]), f'Chapter {chp["chap"]}',
                    i
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return []

    async def get_title(self, raw_url: str) -> str | None:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.apis.comick.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return None
        return manga["comic"]["title"]

    async def get_id(self, raw_url: str) -> str | None:
        async with self.bot.session.get(raw_url) as resp:
            await raise_and_report_for_status(self.bot, resp)
            manga_id = re.search(r"\"hid\":\"([^\"]+)\"", await resp.text()).group(1)
            return manga_id

    async def get_status(self, raw_url: str) -> str:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.apis.comick.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return "Unknown"
        status_map = {1: "Ongoing", 2: "Completed", 3: "Cancelled", 4: "Hiatus"}
        return status_map[manga["comic"]["status"]]

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _: Optional[str] = None
    ) -> str:
        if not url_name:
            url_name = self.rx.search(raw_url).groupdict()["url_name"]
        return self.fmt_url.format(url_name=url_name)

    async def get_cover(self, raw_url: str) -> str | None:
        manga_id = await self.get_id(raw_url)
        return await self.bot.apis.comick.get_cover(manga_id)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        json_resp: list[dict] = await self.bot.apis.comick.search(query=query)
        found_manga: list[PartialManga] = []
        if not json_resp:
            return found_manga

        for item_dict in json_resp:
            title = item_dict["title"]
            _id = item_dict.get("hid")
            if not _id:
                # This means that only similar manhwa are displaed (not what we want)
                continue
            url_name = item_dict["slug"]
            url = await self.format_manga_url(url_name=url_name)
            cover_filename = (item_dict["md_covers"] or [{"b2key": None}])[0]["b2key"]
            cover = f"https://meo.comick.pictures/{cover_filename}"
            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _MangaDex(AbstractScanlator):
    rx: re.Pattern = RegExpressions.mangadex_url
    icon_url = "https://mangadex.org/favicon.ico"
    base_url = "https://mangadex.org"
    fmt_url = base_url + "/title/{manga_id}"
    chp_url_fmt = base_url + "/chapter/{chapter_id}"

    def __init__(self, name: str):
        super().__init__(name)
        self.name: str = name

    @property
    def json_tree(self):
        return SimpleNamespace(
            properties=SimpleNamespace(
                icon_url=self.icon_url,
                base_url=self.base_url,
                requires_update_embed=False,
                can_render_cover=True,
                format_urls=SimpleNamespace(
                    manga=self.fmt_url,
                )
            )
        )

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        return []

    def check_ownership(self, raw_url: str) -> bool:
        return self.rx.search(raw_url) is not None

    async def get_synopsis(self, raw_url: str) -> str:
        manga_id = await self.get_id(raw_url)
        synopsis = await self.bot.apis.mangadex.get_synopsis(manga_id)
        if synopsis:
            return synopsis
        else:
            return "No synopsis found."

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        manga_id = await self.get_id(raw_url)
        chapters = await self.bot.apis.mangadex.get_chapters_list(manga_id)
        if chapters:
            return [
                Chapter(
                    self.chp_url_fmt.format(chapter_id=chp["id"]), f'Chapter {chp["attributes"]["chapter"]}', i,
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return []

    async def get_status(self, raw_url: str) -> str:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.apis.mangadex.get_manga(manga_id)
        status = manga["data"]["attributes"]["status"].lower().capitalize()
        return status

    async def get_title(self, raw_url: str) -> str | None:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.apis.mangadex.get_manga(manga_id)
        return manga["data"]["attributes"]["title"]["en"]

    async def get_id(self, raw_url: str) -> str:
        return self.rx.search(raw_url).groupdict()["id"]

    async def format_manga_url(
            self, raw_url: Optional[str] = None, _: Optional[str] = None, _id: Optional[str] = None
    ) -> str:
        if not any([raw_url is not None, _id is not None]):
            raise ValueError("At least one of the arguments must be provided.")
        manga_id = _id or await self.get_id(raw_url)
        return self.fmt_url.format(manga_id=manga_id)

    async def get_cover(self, raw_url: str) -> str | None:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.apis.mangadex.get_manga(manga_id)
        cover_id = [
            x["id"] for x in manga["data"]["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await self.bot.apis.mangadex.get_cover(manga["data"]["id"], cover_id)
        return cover_url

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        json_resp = await self.bot.apis.mangadex.search(title=query)
        found_manga: list[PartialManga] = []
        if not json_resp["data"]:
            return found_manga

        results: list[dict] = json_resp["data"]
        for item_dict in results:
            attrs_dict = item_dict["attributes"]
            title = attrs_dict["title"].get("en", str(tuple(attrs_dict["title"].values())[0]))
            _id = item_dict["id"]
            url = await self.format_manga_url(_id=_id)
            cover_id: str | None = None
            relationships_dicts: list[dict] = item_dict["relationships"]
            for rel_dict in relationships_dicts:
                if rel_dict["type"] == "cover_art":
                    cover_id = rel_dict["id"]
                    break
            cover = await self.bot.apis.mangadex.get_cover(manga_id=_id, cover_id=cover_id)
            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _ZeroScans(AbstractScanlator):
    rx: re.Pattern = RegExpressions.zeroscans_url
    icon_url = "https://zeroscans.com/favicon.ico"
    base_url = "https://zeroscans.com"
    fmt_url = base_url + "/comics/{url_name}"
    chp_url_fmt = fmt_url + "/{chapter_id}"

    def __init__(self, name: str):
        super().__init__(name)
        self.name: str = name

    @property
    def json_tree(self):
        return SimpleNamespace(
            properties=SimpleNamespace(
                icon_url=self.icon_url,
                base_url=self.base_url,
                requires_update_embed=False,
                can_render_cover=True,
                format_urls=SimpleNamespace(
                    manga=self.fmt_url,
                )
            )
        )

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        new_chapters: list[dict] = await self.bot.apis.zeroscans.get_latest_chapters()
        found_manhwa: list[PartialManga] = []
        for manhwa_dict in new_chapters:
            url_name = manhwa_dict["slug"]
            url = await self.format_manga_url(url_name=url_name)
            manga_id = await self.get_id(url)
            name = manhwa_dict["name"]
            cover = manhwa_dict["cover"]["vertical"]
            latest_chapters: list[Chapter] = []
            for i, chapter_dict in enumerate(manhwa_dict["chapters"]):
                chap = Chapter(
                    self.chp_url_fmt.format(url_name=url_name, chapter_id=chapter_dict["id"]),
                    f'Chapter {chapter_dict["name"]}',
                    i
                )
                latest_chapters.append(chap)
            p_manhwa = PartialManga(
                manga_id, name, url, self.name, cover, latest_chapters
            )
            found_manhwa.append(p_manhwa)
        return found_manhwa

    def check_ownership(self, raw_url: str) -> bool:
        return self.rx.search(raw_url) is not None

    async def _get_url_name(self, raw_url: str) -> str:
        try:
            return self.rx.search(raw_url).groupdict().get("url_name")
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e

    async def get_synopsis(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        return await self.bot.apis.zeroscans.get_synopsis(url_name)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        url_name = await self._get_url_name(raw_url)
        manga_id = await self.bot.apis.zeroscans.get_manga_id(url_name)
        chapters = await self.bot.apis.zeroscans.get_chapters_list(manga_id)
        if chapters:
            url_name = self.rx.search(raw_url).groupdict()["url_name"]
            return [
                Chapter(
                    self.chp_url_fmt.format(
                        url_name=url_name, chapter_id=chp["id"]), f'Chapter {chp["name"]}',
                    i
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return []

    async def get_title(self, raw_url: str) -> str | None:
        url_name = await self._get_url_name(raw_url)
        manga = await self.bot.apis.zeroscans.get_manga(url_name)
        return manga["data"]["name"]

    async def get_id(self, raw_url: str) -> str | None:
        try:
            url_id = self.rx.search(raw_url).groupdict().get("id")
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e
        if url_id is None or self.json_tree.properties.dynamic_url is True:
            key = await self._get_url_name(raw_url)
            return hashlib.sha256(key.encode()).hexdigest()
        return url_id
        # return await self.bot.apis.zeroscans.get_manga_id(await self._get_url_name(raw_url))

    async def get_status(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        manga = await self.bot.apis.zeroscans.get_manga(url_name)
        for status_dict in manga["data"]["statuses"]:
            if status_dict["slug"] == "ongoing":
                return "Ongoing"
        else:
            return manga["data"]["statuses"][-1]["name"] if manga["data"]["statuses"] else "Completed"

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _: Optional[str] = None
    ) -> str:
        if not url_name:
            url_name = self.rx.search(raw_url).groupdict()["url_name"]
        return self.fmt_url.format(url_name=url_name)

    async def get_cover(self, raw_url: str) -> str | None:
        url_name = await self._get_url_name(raw_url)
        return await self.bot.apis.zeroscans.get_cover(url_name)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        json_resp: list[dict] = await self.bot.apis.zeroscans.search(title=query, limit=10)
        found_manga: list[PartialManga] = []
        if not json_resp:
            return found_manga

        for item_dict in json_resp:
            title = item_dict["name"]
            _id = item_dict.get("id")
            url_name = item_dict["slug"]
            url = await self.format_manga_url(url_name=url_name)
            for key in ["full", "vertical", "horizontal"]:
                cover = item_dict["cover"].get(key)
                if cover:
                    break
            else:
                cover = None

            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class CustomKeys:
    comick: str = "comick"
    mangadex: str = "mangadex"
    zeroscans: str = "zeroscans"


keys = CustomKeys()

scanlators[keys.comick] = _Comick(keys.comick)
scanlators[keys.mangadex] = _MangaDex(keys.mangadex)
scanlators[keys.zeroscans] = _ZeroScans(keys.zeroscans)
