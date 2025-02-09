import hashlib
import re
from collections import OrderedDict
from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional

import discord

from src.core.objects import Chapter, ChapterUpdate, Manga, PartialManga
from .classes import AbstractScanlator, scanlators
from ...static import RegExpressions

__all__ = (
    "scanlators",
)


class _Comick(AbstractScanlator):
    rx: re.Pattern = RegExpressions.comick_url
    icon_url = "https://comick.io/static/icons/unicorn-256_maskable.png"
    base_url = "https://comick.io"
    cover_url = "https://meo.comick.pictures/"
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
                ),
                supports_search=True
            ),
            request_method="curl",
            rx=self.rx
        )

    async def get_fp_partial_manga(self) -> list[PartialManga]:
        latest_chapters = await self.bot.apis.comick.get_latest_chapters(page=1, order="new")
        latest_chapters.extend(await self.bot.apis.comick.get_latest_chapters(page=2, order="new"))
        latest_chapters.extend(await self.bot.apis.comick.get_latest_chapters(page=3, order="new"))

        fp_manga: OrderedDict[str, PartialManga] = OrderedDict()

        for chp_dict in latest_chapters:  # going from older to the newest so the order of chapters is asc
            # ---- FP Manga ----
            comic_info = chp_dict["md_comics"]
            _id = comic_info["hid"]
            if _id in fp_manga:  # Ignore any duplicates. Only consider the latest chapter
                # Comick tends to show updates for chapters like these:
                # ['Chapter 229', 'Chapter 282', 'Chapter 308']
                continue
            title = comic_info["title"]
            url_name = comic_info["slug"]
            url = await self.format_manga_url(url_name=url_name)
            cover = self.cover_url + comic_info["md_covers"][0]["b2key"]
            # ---- Chapter ----
            publish_ts = datetime.fromisoformat(chp_dict["publish_at"] or "2023-02-01T16:11:46Z").timestamp()
            now_ts = datetime.now().timestamp()
            ch_index = 0  # if _id not in fp_manga else len(fp_manga[_id].latest_chapters)
            ch_name = chp_dict["chap"] or "Unknown"
            if ch_name == "Unknown" and comic_info["last_chapter"] is not None:
                ch_name = comic_info["last_chapter"]
            chapter = Chapter(
                self.chp_url_fmt.format(url_name=url_name, chapter_id=chp_dict["hid"]),
                f'Chapter {ch_name}',
                ch_index,
                publish_ts > now_ts
            )
            if _id in fp_manga:
                fp_manga[_id].latest_chapters.append(chapter)
            else:
                fp_manga[_id] = PartialManga(_id, title, url, self.name, cover, [chapter], url)

        return list(reversed(fp_manga.values()))

    async def check_updates(
            self,
            manga: Manga,
    ) -> ChapterUpdate:
        """
        Summary:
            Checks whether any new releases have appeared on the scanlator's website.
            Checks whether the series is completed or not.

        Parameters:
            manga: Manga - The manga object to check for updates.

        Returns:
            ChapterUpdate - The update result.

        Raises:
            MangaNotFoundError - If the manga is not found in the scanlator's website.
            URLAccessFailed - If the scanlator's website is blocked by Cloudflare.
        """
        status: str = await self.get_status(manga.url)
        cover_url: str = await self.get_cover(manga.url)
        status_changed: bool = status != manga.status
        url_name = await self._get_url_name(manga.url)

        def _make_chapters(chapters: list[dict]) -> list[Chapter]:
            return [
                Chapter(
                    self.chp_url_fmt.format(url_name=url_name, chapter_id=chp["hid"]), f'Chapter {chp["chap"]}',
                    i,
                    datetime.fromisoformat(
                        chp["publish_at"] or "2023-02-01T16:11:46Z").timestamp() > datetime.now().timestamp()
                )
                for i, chp in enumerate(chapters)  # noqa
            ]

        if not manga.last_chapter:
            new_chapters = await self.get_all_chapters(manga.url)
            update = ChapterUpdate(manga.id, new_chapters, manga.scanlator, cover_url, status, status_changed)
            if self.json_tree.properties.requires_update_embed:
                update.extra_kwargs = [
                    {"embed": self.create_chapter_embed(manga, chapter)}
                    for chapter in new_chapters
                ]
            return update

        newest_chapters: list[Chapter] = []
        _chapters, total_num_chapters = await self.bot.apis.comick.get_chapters_list(manga.id, page_limit=1)
        if not _chapters:
            await self.report_error(Exception(
                f"Expected chapters from comick for {manga}, but got none. (Db) Manga has {len(manga.chapters)} chapters.")
            )
            return ChapterUpdate(manga.id, [], manga.scanlator, cover_url, status, status_changed)
        newest_chapters: list[Chapter] = _make_chapters(_chapters)

        last_free_ch = next((c for c in reversed(manga.chapters) if not c.is_premium), None)
        if last_free_ch.index == manga.last_chapter.index:
            # No paid chapters here
            ch_to_find = manga.last_chapter
        elif last_free_ch is None:
            # All are paid chapters
            ch_to_find = None  # If it's none, we need to look for the last free web chapter
        else:  # There are some free and some paid chapters
            ch_to_find = last_free_ch

        def _find_web_ch_index():
            for i, ch in reversed(list(enumerate(newest_chapters))):  # noqa
                if ch_to_find is not None:
                    if ch.name == ch_to_find.name:
                        return i
                elif not ch.is_premium:  # look for the last free chapter
                    return i
            return -1

        page = 1

        while True:
            _web_index = _find_web_ch_index()
            if _web_index != -1 or len(newest_chapters) == total_num_chapters:
                break
            page += 1
            result, _ = await self.bot.apis.comick.get_chapters_list(manga.id, page=page, page_limit=1)
            result = _make_chapters(result)
            if not result:  # _web_index = -1 atp
                break
            # the below is the same as: newest_chapters = result + newest_chapters
            result.extend(newest_chapters)
            newest_chapters = result

        """
        Logic behind the nonsense below:
        
        (Db) No paid chapters
            - get (db) latest, find it's index in newest_chapters.
            - newest_chapters[(db)latest.index+1:] = updates
        
        (Db) There are paid chapters
            (Db) There are free and paid chapters
                -find (db) last free.
                -find its index in newest_chapters
                -fix the index of newest_chapters
                -updated chapters are ones that have index > (db)last free.index and <= (db).latest that are (db) premium and (web) free
                -new uploads are chapters with index > (db) last
            
            (Db) All are paid chapters
                -request until (web) last free chapter
                (Web) No last free - all (web) chapters are paid
                    - find (web) last index in (db)
                    - fix index for newest_chapters
                    - everything from db.latest.index > is an update
        
                (Web) last free not none
                    -find first free in (db)
                    -fix index from first_free up in web
                    -everything from start up to and including (web) first free is an update.
                    -everything from (db) latest .index +(excluding) is an update
        """

        if _web_index == -1:  # we have all chapters from the website
            for i, ch in enumerate(newest_chapters):
                ch.index = i
            # We were looking for the last free chapter, but we didn't find it.
            if ch_to_find is None:
                new_chapters = newest_chapters[manga.last_chapter.index + 1:]
            else:
                raise Exception("Tried looking for a chapter but we never found it...")
        else:  # We found (web) last free chapter OR ch_to_find
            # Fix the chapters for newest_chapters
            try:
                start_idx = next(
                    i for i, c in enumerate(manga.chapters) if c.name.lower() == newest_chapters[0].name.lower()
                )
            except StopIteration as e:
                print(f"Was looking for {newest_chapters[0].url} in manga: {manga.url} {manga.chapters}")
                raise e
            for i, ch in enumerate(newest_chapters):
                ch.index = start_idx + i

            if ch_to_find is None:
                # We were looking for the (web) last free chapter, and we found it.
                new_chapters = [c for i, c in enumerate(manga.chapters)
                                if c.is_premium and i <= newest_chapters[_web_index].index
                                ]
                new_chapters.extend([c for c in newest_chapters if c.index > manga.last_chapter.index])
            else:  # We were looking for ch_to_find, and we found it
                # ch_to_find = (db) last_free_ch
                # ch_to_find = (db) manga.last_ch
                if ch_to_find.index == manga.last_chapter.index:
                    # No paid chapters here
                    new_chapters = [c for c in newest_chapters if c.index > newest_chapters[_web_index].index]
                else:
                    # There are some free and some paid chapters
                    new_chapters = [c for i, c in enumerate(newest_chapters)
                                    if newest_chapters[
                                        _web_index].index < c.index <= manga.last_chapter.index and not c.is_premium
                                    ]
                    new_chapters.extend([c for c in newest_chapters if c.index > manga.last_chapter.index])

        return ChapterUpdate(  # noqa
            manga.id, new_chapters, manga.scanlator, cover_url, status, status_changed,
            extra_kwargs=[
                {"embed": self.create_chapter_embed(manga, chapter)}
                for chapter in new_chapters
            ] if self.json_tree.properties.requires_update_embed else None
        )

    def check_ownership(self, raw_url: str) -> bool:
        return self.rx.search(raw_url) is not None

    async def get_synopsis(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        return await self.bot.apis.comick.get_synopsis(url_name)

    async def get_all_chapters(self, raw_url: str) -> list[Chapter] | None:
        manga_id = await self.get_id(raw_url)
        chapters, _ = await self.bot.apis.comick.get_chapters_list(manga_id)
        if chapters:
            url_name = await self._get_url_name(raw_url)
            return [
                Chapter(
                    self.chp_url_fmt.format(
                        url_name=url_name, chapter_id=chp["hid"]), f'Chapter {chp["chap"]}',
                    i,
                    datetime.fromisoformat(
                        chp["publish_at"] or "2023-02-01T16:11:46Z"  # using an arbitrary value in the past
                    ).timestamp() > datetime.now().timestamp()
                )
                for i, chp in enumerate(chapters)
            ]
        else:
            return []

    async def _get_url_name(self, raw_url: str) -> str:
        try:
            return self.rx.search(raw_url).groupdict().get("url_name")
        except (AttributeError, TypeError) as e:
            self.bot.logger.error(raw_url)
            raise e

    async def _get_and_update_manga_obj(self, url_name: str) -> dict:
        manga_dict = await self.bot.apis.comick.get_manga(url_name)
        new_prefix = manga_dict.get("new_prefix")
        if new_prefix is None:
            return manga_dict

        _manga_id = manga_dict["comic"]["hid"]  # This is the same implementation as ComickAppAPI.get_id
        db_manga = await self.bot.db.get_series(_manga_id, self.name)

        if db_manga is None:  # no idea why, but adding this anyway
            return manga_dict

        rx = re.compile(r'/comic/(0\d-)?')
        db_manga._url = rx.sub('/comic/' + new_prefix + '-', db_manga._url)
        for chp in db_manga.chapters:
            chp.url = rx.sub('/comic/' + new_prefix + '-', chp.url)
        if db_manga.last_chapter:
            db_manga.last_chapter.url = rx.sub('/comic/' + new_prefix + '-', db_manga.last_chapter.url)

        await self.bot.db.update_series(db_manga)
        return manga_dict

    async def get_title(self, raw_url: str) -> str | None:
        url_name = await self._get_url_name(raw_url)
        manga = await self._get_and_update_manga_obj(url_name)
        if manga.get("statusCode", 200) == 404:
            return None
        return manga["comic"]["title"]

    async def get_id(self, raw_url: str) -> str | None:
        url_name = await self._get_url_name(raw_url)
        return await self.bot.apis.comick.get_id(url_name)

    async def get_status(self, raw_url: str) -> str:
        url_name = await self._get_url_name(raw_url)
        manga = await self._get_and_update_manga_obj(url_name)
        if manga.get("statusCode", 200) == 404:
            return "Unknown"
        status_map = {1: "Ongoing", 2: "Completed", 3: "Cancelled", 4: "Hiatus"}
        return status_map[manga["comic"]["status"]]

    async def format_manga_url(
            self, raw_url: Optional[str] = None, url_name: Optional[str] = None, _: Optional[str] = None
    ) -> str:
        if not url_name:
            url_name = await self._get_url_name(raw_url)
        return self.fmt_url.format(url_name=url_name)

    async def get_cover(self, raw_url: str) -> str | None:
        url_name = await self._get_url_name(raw_url)
        return self.cover_url + await self.bot.apis.comick.get_cover_filename(url_name)

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
            cover_filename = str((item_dict["md_covers"] or [{"b2key": None}])[0]["b2key"])
            cover = self.cover_url + cover_filename
            p_manga = PartialManga(_id, title, url, self.name, cover_url=cover)
            found_manga.append(p_manga)
        if as_em:
            found_manga: list[discord.Embed] = self.partial_manga_to_embed(found_manga)
        return found_manga


class _MangaDex(AbstractScanlator):
    rx: re.Pattern = RegExpressions.mangadex_url
    icon_url = "https://mangadex.org/favicon.ico"
    base_url = "https://mangadex.org"
    fmt_url = base_url + "/title/{id}"
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
                ),
                supports_search=True
            ),
            request_method="curl",
            rx=self.rx
        )

    async def format_manga_url(
            self, raw_url: Optional[str] = None, _: Optional[str] = None, _id: Optional[str] = None
    ) -> str:
        if not any([raw_url is not None, _id is not None]):
            raise ValueError("At least one of the arguments must be provided.")
        manga_id = _id or await self.get_id(raw_url)
        return self.fmt_url.format(id=manga_id)

    def check_ownership(self, raw_url: str) -> bool:
        return self.rx.search(raw_url) is not None

    async def get_fp_partial_manga(self) -> List[PartialManga]:
        # Get the latest chapters from MangaDex.
        # No need for page numbers;
        # the API client uses offset (default offset=0, limit=32, etc.).
        latest_chapters = (await self.bot.apis.mangadex.get_latest_chapters()).get("data", [])

        # We'll group chapters by manga id.
        fp_manga: OrderedDict[str, PartialManga] = OrderedDict()

        for chp in latest_chapters:
            # Extract the manga relationship from the chapter's relationships.
            manga_rel = next(
                (rel for rel in chp.get("relationships", []) if rel.get("type") == "manga"),
                None
            )
            if not manga_rel:
                continue

            manga_id = manga_rel["id"]
            if manga_id in fp_manga:
                # Skip duplicates: only keep the first (i.e. latest) chapter for each manga.
                continue

            # Extract manga title.
            title_dict = manga_rel.get("attributes", {}).get("title", {})
            # Prefer the English title if available; otherwise take any.
            manga_title = title_dict.get("en") or (next(iter(title_dict.values()), "Unknown Title"))

            # Construct the manga URL (using a common MangaDex URL format).
            manga_url = await self.format_manga_url(_id=manga_id)

            # Get chapter attributes.
            attrs = chp.get("attributes", {})
            # Normally if the chapter is a oneshot, it won't have a chapter number.
            ch_name = 'Chapter ' + (attrs.get("chapter") or "Oneshot")
            chapter_url = self.chp_url_fmt.format(chapter_id=chp["id"])
            readable_at = attrs.get("readableAt", "1970-01-01T00:00:00+00:00")
            readable_at_ts = datetime.fromisoformat(readable_at).timestamp()
            now_ts = datetime.now().timestamp()

            chapter = Chapter(chapter_url, ch_name, 0, readable_at_ts > now_ts)

            fp_manga[manga_id] = PartialManga(manga_id, manga_title, manga_url, self.name, None, [chapter])

        return list(fp_manga.values())

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
    icon_url = "https://zscans.com/favicon.ico"
    base_url = "https://zscans.com"
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
                ),
                supports_search=True
            ),
            request_method="curl",
            rx=self.rx
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
