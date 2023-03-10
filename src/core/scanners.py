from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import re

from bs4 import BeautifulSoup

from src.static import RegExpressions

from .errors import MangaNotFoundError
import hashlib
from abc import ABC, abstractmethod
from src.utils import _hash


class ChapterUpdate:
    def __init__(self, new_chapter_url: str, new_chapter_string: str, series_completed: bool = False):
        self.new_chapter_url = new_chapter_url
        self.new_chapter_string = self._fix_chapter_string(new_chapter_string)
        self.series_completed = series_completed
        self.url_chapter_hash = _hash(new_chapter_url)

    @staticmethod
    def _fix_chapter_string(chapter_string: str) -> str:
        """Fixes the chapter string to be more readable."""
        result = chapter_string.replace("\n", " ").replace("Ch.", "Chapter")
        return re.sub(r"\s+", " ", result).strip()

    def __repr__(self):
        return f"UpdateResult({self.new_chapter_string} - {self.new_chapter_url})"


class ABCScan(ABC):
    MIN_TIME_BETWEEN_REQUESTS = 1.0  # In seconds
    base_url: str = None
    fmt_url: str = None
    name: str = "Unknown"

    @classmethod
    @abstractmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url_hash: str,
    ) -> list[ChapterUpdate]:
        """
        Summary:

        Checks whether any new releases have appeared on the scanlator's website.
        Checks whether the series is completed or not.

        Parameters:

        bot: MangaClient - The bot instance.
        human_name: str - The name of the manga.
        manga_url: str - The URL of the manga's home page.
        manga_id: str - The ID of the manga.
        last_chapter_url_hash: str - The hash of the last released chapter url (last time).

        Returns:
        list[ChapterUpdate] - A list of ChapterUpdate objects containing the following:
            :str/None: - The `url` of the new chapter if a new release appeared, otherwise `None`.
            :str/None: - The `chapter text` of the new chapter if a new release appeared, otherwise `None`.
            :bool: - `True` if the series is completed, otherwise `False`.
            :str/None: - The url hash of the new chapter if a new release appeared, otherwise `None`.

        Raises:

        MangaNotFoundError - If the manga is not found in the scanlator's website.

        Notes:
            After looking at more manga and their chapter lists, I've noticed that the chapter numbers are not always
            present. Moving forward the chapter number will be the hash of the chapter URL. This will be used to
            determine whether a new chapter has been released or not.
            This also means that the behaviour of the "check_updates" task needs to be changed as well.
        """
        raise NotImplementedError

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """
        Summary:

        Checks whether a series is completed or not.

        Parameters:

        soup: BeautifulSoup - The soup object to check the series status.

        Returns:

        bool - `True` if the series is completed, otherwise `False`.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        """
        Summary:

        Checks whether a series is completed or not.

        Parameters:

        session: aiohttp.ClientSession - The session to use for the request.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        bool - `True` if the series is completed, otherwise `False`.

        Raises:

        MangaNotFoundError - If the manga is not found in the scanlator's website.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str:
        """
        Summary:

        Gets the human-readable name of the manga.

        Parameters:

        bot: MangaClient - The bot instance.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        str - The human-readable name of the manga.

        Raises:

        MangaNotFoundError - If the manga is not found in the scanlator's website.
        """
        raise NotImplementedError

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        """
        Summary:

        Gets the ID of the manga.

        Parameters:

        manga: str - The URL of the manga.

        Returns:

        str - The ID of the manga.
        """
        return hashlib.sha256(manga_url.encode()).hexdigest()

    @classmethod
    @abstractmethod
    async def get_curr_chapter_text(
            cls,
            bot: MangaClient,
            manga_id: str,
            manga_url: str) -> str | None:
        """
        Summary:

        Gets the current chapter text of the manga.

        Parameters:

        bot: MangaClient - The bot instance.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        str/None - The current chapter text of the manga.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def get_curr_chapter_url_hash(
            cls,
            bot: MangaClient,
            manga_id: str,
            manga_url: str,
    ) -> str | None:
        """
        Summary:

        Gets the hash of the current chapter URL of the manga.

        Parameters:

        bot: MangaClient - The bot instance.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        str/None - The hash of the current chapter URL of the manga.
        """
        raise NotImplementedError


class TritiniaScans(ABCScan):

    base_url = "https://tritinia.org/manga/"
    fmt_url = base_url + "{manga}/ajax/chapters/"
    name = "tritinia"

    @staticmethod
    def _ensure_manga_url(url: str) -> str:
        if url.endswith("/") and "/ajax/chapters/" not in url:
            url = url[:-1]
        return url + "/ajax/chapters/"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url_hash: str,
    ) -> list[ChapterUpdate] | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                bot.logger.error("Tritinia: Failed to get manga page", resp.status)
                return None
            text = await resp.text()

            completed = await cls.is_series_completed(bot, manga_id, manga_url)

            soup = BeautifulSoup(text, "html.parser")
            last_chapter_containers = soup.find_all("li", {"class": "wp-manga-chapter"})
            new_updates: list[ChapterUpdate] = []

            for chap_container in last_chapter_containers:
                last_chapter_tag = chap_container.find("a")
                new_url = last_chapter_tag["href"]
                new_url_hash = _hash(new_url)
                new_chapter_text = last_chapter_tag.text

                if new_url_hash == last_chapter_url_hash:
                    break
                chapter_update = ChapterUpdate(new_url, new_chapter_text, completed)
                new_updates.append(chapter_update)

            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url_hash(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            last_chapter_container = soup.find("li", {"class": "wp-manga-chapter"})
            last_chapter_tag = last_chapter_container.find("a")

            new_url = last_chapter_tag["href"]
            last_url_hash = _hash(new_url)
            return last_url_hash

    @classmethod
    async def get_curr_chapter_text(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            last_chapter_container = soup.find("li", {"class": "wp-manga-chapter"})
            last_chapter_tag = last_chapter_container.find("a")

            new_chapter_text = last_chapter_tag.text.strip().replace("Ch.", "Chapter")
            return new_chapter_text

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        status_div = status_container.find_all("div", {"class": "post-content_item"})[1]
        status = status_div.find("div", {"class": "summary-content"})
        status = status.text.strip()

        return status.lower() == "completed"

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                raise MangaNotFoundError(manga_url=manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "post-title"})
            title = title_div.find("h1")
            span_found = title.find("span")
            if span_found:
                span_found.decompose()
            return title.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        hash_object = hashlib.sha1(manga_url.encode())
        return hash_object.hexdigest()


class Manganato(ABCScan):
    base_url = "https://chapmanganato.com/manga-"
    fmt_url = base_url + "{manga_id}"
    name = "manganato"

    @classmethod
    async def check_updates(cls, bot: MangaClient, human_name: str, manga_url: str, manga_id: str,
                            last_chapter_url_hash: str) -> list[ChapterUpdate] | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                bot.logger.error("Manganato: Failed to get manga page", resp.status)
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            completed = cls._bs_is_series_completed(soup)
            new_updates: list[ChapterUpdate] = []

            chapter_list_container = soup.find(
                "div", {"class": "panel-story-chapter-list"}
            )
            chapter_tags = chapter_list_container.find_all("a")
            for chp_tag in chapter_tags:
                new_chapter_url = chp_tag["href"]
                new_chapter_text = chp_tag.text

                if _hash(new_chapter_url) == last_chapter_url_hash:
                    break
                new_chapter_update = ChapterUpdate(new_chapter_url, new_chapter_text, completed)
                new_updates.append(new_chapter_update)

            return list(reversed(new_updates))

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
        return status.lower() == "completed"

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                raise MangaNotFoundError(manga_url)

            text = await resp.text()

            if "404 - PAGE NOT FOUND" in text:
                raise MangaNotFoundError(manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "story-info-right"})
            return title_div.find("h1").text.strip()

    @classmethod
    async def get_curr_chapter_url_hash(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "div", {"class": "panel-story-chapter-list"}
            )
            last_chapter_link = chapter_list_container.find("a")
            last_chapter_url = last_chapter_link["href"]
            return _hash(last_chapter_url) if last_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "div", {"class": "panel-story-chapter-list"}
            )
            last_chapter_link = chapter_list_container.find("a")
            return last_chapter_link.text.strip() if last_chapter_link else None

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return re.search(r"manga-(.*)", manga_url).group(1)


class Toonily(ABCScan):
    base_url = "https://toonily.com/webtoon/"
    fmt_url = base_url + "{manga_url_name}"
    name = "toonily"

    @classmethod
    async def check_updates(cls, bot: MangaClient, human_name: str, manga_url: str, manga_id: str,
                            last_chapter_url_hash: str) -> list[ChapterUpdate] | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                bot.logger.error("Toonily: Failed to get manga page", resp.status)
                return None

            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            completed = cls._bs_is_series_completed(soup)
            new_updates: list[ChapterUpdate] = []

            chapter_list_container = soup.find(
                "ul", {"class": "main version-chap no-volumn"}
            )
            new_chapter_links = chapter_list_container.find_all("a")
            for chp_link in new_chapter_links:
                new_chapter_url = chp_link["href"]
                new_chapter_text = chp_link.text
                new_chapter_url_hash = _hash(new_chapter_url)

                if new_chapter_url_hash == last_chapter_url_hash:
                    break
                new_chapter_update = ChapterUpdate(new_chapter_url, new_chapter_text, completed)
                new_updates.append(new_chapter_update)

            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url_hash(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "ul", {"class": "main version-chap no-volumn"}
            )
            last_chapter_link = chapter_list_container.find("a")
            last_chapter_url = last_chapter_link["href"]

            return _hash(last_chapter_url) if last_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "ul", {"class": "main version-chap no-volumn"}
            )
            last_chapter_link = chapter_list_container.find("a")
            return last_chapter_link.text.strip() if last_chapter_link else None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "post-status"})
        status_div = status_container.find_all("div", {"class": "post-content_item"})[1]
        status = status_div.find("div", {"class": "summary-content"})
        status = status.text.strip()

        return status.lower() == "completed"

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                raise MangaNotFoundError(manga_url=manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "post-title"})
            title = title_div.find("h1")
            span_found = title.find("span")
            if span_found:
                span_found.decompose()
            return title.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return super().get_manga_id(manga_url)


class MangaDex(ABCScan):
    base_url = "https://mangadex.org/"
    fmt_url = base_url + "title/{manga_id}"
    name = "mangadex"

    @classmethod
    async def check_updates(cls, bot: MangaClient, human_name: str, manga_url: str, manga_id: str,
                            last_chapter_url_hash: str) -> list[ChapterUpdate] | None:

        chapters = await bot.mangadex_api.get_chapters_list(manga_id)

        completed = await cls.is_series_completed(bot, manga_id, manga_url)
        new_updates: list[ChapterUpdate] = []
        high_to_low = reversed(chapters)

        for new_chp in high_to_low:
            chp_id_hash = _hash(new_chp["id"])
            if chp_id_hash == last_chapter_url_hash:
                break
            new_chapter_upate = ChapterUpdate(
                "https://mangadex.org/chapter/" + new_chp["id"],
                f'Chapter {new_chp["attributes"]["chapter"]}',
                completed,
                )
            new_updates.append(new_chapter_upate)

        return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url_hash(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        chapters = await bot.mangadex_api.get_chapters_list(manga_id)
        return _hash(chapters[-1]["id"]) if chapters else None

    @classmethod
    async def get_curr_chapter_text(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        chapters = await bot.mangadex_api.get_chapters_list(manga_id)
        return ("Chapter " + chapters[-1]["attributes"]["chapter"]) if chapters else None

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        manga = await bot.mangadex_api.get_manga(manga_id)
        return manga["data"]["attributes"]["status"] == "completed"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        manga = await bot.mangadex_api.get_manga(manga_id)
        return manga["data"]["attributes"]["title"]["en"]

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.mangadex_url.search(manga_url).group(3)

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        pass


class FlameScans(ABCScan):
    base_url = "https://flamescans.org/"
    fmt_url = base_url + "series/{manga_id}-{manga_url_name}"
    name = "flamescans"

    @classmethod
    async def check_updates(cls, bot: MangaClient, human_name: str, manga_url: str, manga_id: str,
                            last_chapter_url_hash: str) -> list[ChapterUpdate] | None:

        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find_all("a")
            new_updates: list[ChapterUpdate] = []

            for chapter in chapter_list:
                chapter_url = chapter["href"]
                chapter_text = chapter.find("span", {"class": "chapternum"}).text.replace("\n", " ").strip()

                new_chapter_url_hash = _hash(chapter_url)
                if new_chapter_url_hash == last_chapter_url_hash:
                    break
                new_chapter_update = ChapterUpdate(
                    chapter_url,
                    chapter_text,
                    cls._bs_is_series_completed(soup),
                )
                new_updates.append(
                    new_chapter_update
                )
            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url_hash(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapters_list = chapter_list_container.find_all("a")
            newest_chapter = chapters_list[0]
            newest_chapter_url = newest_chapter["href"]
            newest_chapter_hash = _hash(newest_chapter_url)
            return newest_chapter_hash

    @classmethod
    async def get_curr_chapter_text(cls, bot: MangaClient, manga_id: str, manga_url: str) -> str | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapters_list = chapter_list_container.find_all("a")
            newest_chapter = chapters_list[0]
            newest_chapter_text = newest_chapter.find("span", {"class": "chapternum"}).text.replace("\n", " ").strip()
            return newest_chapter_text if newest_chapter_text else None

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div = soup.find("div", {"class": "imptdt"})
        status = status_div.text.strip()
        return status.lower() == "completed" or status.lower() == "dropped"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_tag = soup.find("h1", {"class": "entry-title"})
            return title_tag.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.flamescans_url.search(manga_url).group(4)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(
                manga_url
        ) as resp:
            if resp.status != 200:
                raise MangaNotFoundError(manga_url=manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)


SCANLATORS: dict[str, ABCScan] = {
    Toonily.name: Toonily,
    TritiniaScans.name: TritiniaScans,
    Manganato.name: Manganato,
    MangaDex.name: MangaDex,
    FlameScans.name: FlameScans,
}
