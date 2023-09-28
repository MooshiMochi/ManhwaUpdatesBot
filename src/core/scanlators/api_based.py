import re
from types import SimpleNamespace
from typing import Optional

import discord

from src.core.objects import Chapter, PartialManga
from .classes import AbstractScanlator, scanlators
from ...static import RegExpressions

__all__ = (
    "scanlators",
)


class _Comick(AbstractScanlator):
    rx: re.Pattern = RegExpressions.comick_url
    icon_url = "https://comick.app/static/icons/unicorn-256_maskable.png"
    base_url = "https://comick.app"
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
        return await self.bot.comick_api.get_synopsis(manga_id)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        manga_id = await self.get_id(raw_url)
        chapters = await self.bot.comick_api.get_chapters_list(manga_id)
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
        manga = await self.bot.comick_api.get_manga(manga_id)
        if manga.get("statusCode", 200) == 404:
            return None
        return manga["comic"]["title"]

    async def get_id(self, raw_url: str) -> str | None:
        async with self.bot.session.get(raw_url) as resp:
            resp.raise_for_status()
            manga_id = re.search(r"\"hid\":\"([^\"]+)\"", await resp.text()).group(1)
            return manga_id

    async def get_status(self, raw_url: str) -> str:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.comick_api.get_manga(manga_id)
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
        return await self.bot.comick_api.get_cover(manga_id)

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        json_resp: list[dict] = await self.bot.comick_api.search(query=query)
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
            cover = (item_dict["md_covers"] or [{"b2key": None}])[0]["b2key"]
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
        synopsis = await self.bot.mangadex_api.get_synopsis(manga_id)
        if synopsis:
            return synopsis
        else:
            return "No synopsis found."

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        manga_id = await self.get_id(raw_url)
        chapters = await self.bot.mangadex_api.get_chapters_list(manga_id)
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
        manga = await self.bot.mangadex_api.get_manga(manga_id)
        status = manga["data"]["attributes"]["status"].lower().capitalize()
        return status

    async def get_title(self, raw_url: str) -> str | None:
        manga_id = await self.get_id(raw_url)
        manga = await self.bot.mangadex_api.get_manga(manga_id)
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
        manga = await self.bot.mangadex_api.get_manga(manga_id)
        cover_id = [
            x["id"] for x in manga["data"]["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await self.bot.mangadex_api.get_cover(manga["data"]["id"], cover_id)
        return cover_url

    async def search(self, query: str, as_em: bool = False) -> list[PartialManga] | list[discord.Embed]:
        json_resp = await self.bot.mangadex_api.search(title=query)
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
            cover = await self.bot.mangadex_api.get_cover(manga_id=_id, cover_id=cover_id)
            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class CustomKeys:
    comick: str = "comick"
    mangadex: str = "mangadex"


keys = CustomKeys()

scanlators[keys.comick] = _Comick(keys.comick)
scanlators[keys.mangadex] = _MangaDex(keys.mangadex)
