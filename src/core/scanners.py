from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.bot import MangaClient

import discord
import hashlib
import re
from abc import ABC, abstractmethod

from bs4 import BeautifulSoup

from src.static import RegExpressions
from src.utils import write_to_discord_file

from .errors import MangaNotFoundError


class ChapterUpdate:
    def __init__(
            self,
            new_chapter_url: str,
            new_chapter_string: str,
            series_completed: bool = False,
            **extra_kwargs
    ):
        self.new_chapter_url = new_chapter_url
        self.new_chapter_string = self._fix_chapter_string(new_chapter_string)
        self.series_completed = series_completed
        self.extra_kwargs = extra_kwargs

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
    async def report_error(cls, bot: MangaClient, error: Exception, **kwargs) -> None:
        message: str = f"Error in {cls.name} scan: {error}"
        await bot.log_to_discord(message, **kwargs)

    @classmethod
    @abstractmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
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
        last_chapter_url: str - The last released chapter url (last time).

        Returns:
        list[ChapterUpdate] - A list of ChapterUpdate objects containing the following:
            :str/None: - The `url` of the new chapter if a new release appeared, otherwise `None`.
            :str/None: - The `chapter text` of the new chapter if a new release appeared, otherwise `None`.
            :bool: - `True` if the series is completed, otherwise `False`.
            :str/None: - The new chapter url if a new release appeared, otherwise `None`.

        Raises:

        MangaNotFoundError - If the manga is not found in the scanlator's website.
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

        Checks whether a series is completed/dropped or not.

        Parameters:

        session: aiohttp.ClientSession - The session to use for the request.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        bool - `True` if the series is completed/dropped, otherwise `False`.

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
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
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
    async def get_curr_chapter_url(
            cls,
            bot: MangaClient,
            manga_id: str,
            manga_url: str,
    ) -> str | None:
        """
        Summary:

        Gets the latest chapter URL of the manga.

        Parameters:

        bot: MangaClient - The bot instance.
        manga_id: str - The ID of the manga.
        manga_url: str - The URL of the manga's home page.

        Returns:

        str/None - The current chapter URL of the manga.
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
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                bot.logger.error("Tritinia: Failed to get manga page", resp.status)
                return await cls.report_error(
                    bot, Exception("Failed to run check_updates func. Status: " + str(resp.status)),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )
            text = await resp.text()

            completed = await cls.is_series_completed(bot, manga_id, manga_url)

            soup = BeautifulSoup(text, "html.parser")
            last_chapter_containers = soup.find_all("li", {"class": "wp-manga-chapter"})
            new_updates: list[ChapterUpdate] = []

            for chap_container in last_chapter_containers:
                last_chapter_tag = chap_container.find("a")
                new_url = last_chapter_tag["href"]
                new_chapter_text = last_chapter_tag.text

                if new_url == last_chapter_url:
                    break
                chapter_update = ChapterUpdate(new_url, new_chapter_text, completed)
                new_updates.append(chapter_update)

            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )
            text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            last_chapter_container = soup.find("li", {"class": "wp-manga-chapter"})
            last_chapter_tag = last_chapter_container.find("a")

            new_url = last_chapter_tag["href"]
            return new_url

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.post(cls._ensure_manga_url(manga_url)) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_text func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )
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
        status = status.text.strip().lower()

        return status == "completed" or status == "dropped" or status == "canceled"

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
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

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


class Manganato(ABCScan):
    base_url = "https://chapmanganato.com/manga-"
    fmt_url = base_url + "{manga_id}"
    name = "manganato"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                bot.logger.error("Manganato: Failed to get manga page", resp.status)
                return await cls.report_error(
                    bot, Exception("Failed to run check_updates func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

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

                if new_chapter_url == last_chapter_url:
                    break
                new_chapter_update = ChapterUpdate(
                    new_chapter_url, new_chapter_text, completed
                )
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
        status = status.lower()
        return status == "completed" or status == "dropped"  # even though manganato doesn't have dropped series

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
                return await cls.report_error(
                    bot, Exception("Failed to run get_human_name func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_div = soup.find("div", {"class": "story-info-right"})
            return title_div.find("h1").text.strip()

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "div", {"class": "panel-story-chapter-list"}
            )
            last_chapter_link = chapter_list_container.find("a")
            last_chapter_url = last_chapter_link["href"]
            return last_chapter_url if last_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_text func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "div", {"class": "panel-story-chapter-list"}
            )
            last_chapter_link = chapter_list_container.find("a")
            return last_chapter_link.text.strip() if last_chapter_link else None

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.manganato_url.search(manga_url).group(1)


class Toonily(ABCScan):
    base_url = "https://toonily.com/webtoon/"
    fmt_url = base_url + "{manga_url_name}"
    name = "toonily"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                bot.logger.error("Toonily: Failed to get manga page", resp.status)
                return await cls.report_error(
                    bot, Exception("Failed to run check_updates func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

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

                if new_chapter_url == last_chapter_url:
                    break
                new_chapter_update = ChapterUpdate(
                    new_chapter_url, new_chapter_text, completed
                )
                new_updates.append(new_chapter_update)

            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find(
                "ul", {"class": "main version-chap no-volumn"}
            )
            last_chapter_link = chapter_list_container.find("a")
            last_chapter_url = last_chapter_link["href"]

            return last_chapter_url if last_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_text func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

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
        status = status.text.strip().lower()

        return status == "completed" or status == "canceled"

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
                return await cls.report_error(
                    bot, Exception("Failed to run get_human_name func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

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
    chp_url_fmt = base_url + "chapter/{chapter_id}"
    name = "mangadex"

    @classmethod
    def _ensure_chp_url_was_in_chapters_list(cls, last_chapter_url: str, chapters_list: list[dict[str, str]]) -> bool:
        for chp in chapters_list:
            chp_id = chp["id"]
            curr_chp_url = cls.chp_url_fmt.format(chapter_id=chp_id)
            if curr_chp_url == last_chapter_url:
                return True
        return False

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        chapters = await bot.mangadex_api.get_chapters_list(manga_id)

        completed = await cls.is_series_completed(bot, manga_id, manga_url)
        new_updates: list[ChapterUpdate] = []
        high_to_low = reversed(chapters)

        if not cls._ensure_chp_url_was_in_chapters_list(last_chapter_url, chapters):
            # this is dirty work, but I can't think of any other way to fix it.
            latest_chapter_available = list(high_to_low)[0]
            chp_url = cls.chp_url_fmt.format(chapter_id=latest_chapter_available["id"])
            chp_text = f'Chapter {latest_chapter_available["attributes"]["chapter"]}'
            new_updates.append(ChapterUpdate(chp_url, chp_text, completed))
            return new_updates

        for new_chp in high_to_low:
            chp_id = new_chp["id"]
            new_chp_url = cls.chp_url_fmt.format(chapter_id=chp_id)
            if new_chp_url == last_chapter_url:
                break
            new_chapter_update = ChapterUpdate(
                new_chp_url,
                f'Chapter {new_chp["attributes"]["chapter"]}',
                completed,
            )
            new_updates.append(new_chapter_update)

        return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        chapters = await bot.mangadex_api.get_chapters_list(manga_id)
        if chapters:
            chp_id = chapters[-1]["id"]
            return cls.chp_url_fmt.format(chapter_id=chp_id)
        else:
            return None

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        chapters = await bot.mangadex_api.get_chapters_list(manga_id)
        return (
            ("Chapter " + chapters[-1]["attributes"]["chapter"]) if chapters else None
        )

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
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.mangadex_url.search(manga_url).group(1)

    @staticmethod
    def _bs_is_series_completed(soup: BeautifulSoup) -> bool:
        return super()._bs_is_series_completed(soup)


class FlameScans(ABCScan):
    base_url = "https://flamescans.org/"
    fmt_url = base_url + "series/{manga_url_name}"
    name = "flamescans"

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
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception(
                        "Failed to run check_updates func. Status: " + str(resp.status)
                    ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find_all("a")
            new_updates: list[ChapterUpdate] = []

            for chapter in chapter_list:
                chapter_url = chapter["href"]
                chapter_url = cls._fix_chapter_url(chapter_url)

                chapter_title = chapter.find("span", {"class": "chapternum"})
                chapter_title = chapter_title.text.replace("\n", " ").strip()

                if chapter_url == last_chapter_url:
                    break

                new_chapter_update = ChapterUpdate(
                    chapter_url, chapter_title, cls._bs_is_series_completed(soup)
                )
                new_updates.append(new_chapter_update)
            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find("a")
            chapter_url = chapter_list["href"]
            chapter_url = cls._fix_chapter_url(chapter_url)
            return chapter_url

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_text func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find("a")
            chapter_title = chapter_list.find("span", {"class": "chapternum"})
            return chapter_title.text.replace("\n", " ").strip() if chapter_title else None

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
            if resp.status != 200:
                await cls.report_error(
                    bot, Exception("Failed to run is_series_completed func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )
                raise MangaNotFoundError(manga_url=manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                raise MangaNotFoundError(manga_url=manga_url)

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return soup.find("h1", {"class": "entry-title"}).text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return super().get_manga_id(manga_url)


class AsuraScans(ABCScan):
    base_url = "https://www.asurascans.com/"
    fmt_url = base_url + "manga/{manga_id}-{manga_url_name}"
    name = "asurascans"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        content = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not content or "Ray ID" in content:
            return await cls.report_error(
                bot, Exception("Failed to run check_updates func. Status: N/A"),
                file=write_to_discord_file(cls.name + '.html', content)
            )

        soup = BeautifulSoup(content, "html.parser")
        chapter_list_container = soup.find("div", {"class": "eplister"})
        chapter_list = chapter_list_container.find_all("a")
        new_updates: list[ChapterUpdate] = []

        for chapter in chapter_list:
            chapter_url = chapter["href"]
            chapter_text = (
                chapter.find("span", {"class": "chapternum"})
                .text.replace("\n", " ")
                .strip()
            )

            if chapter_url == last_chapter_url:
                break
            new_chapter_update = ChapterUpdate(
                chapter_url,
                chapter_text,
                cls._bs_is_series_completed(soup),
            )
            new_updates.append(new_chapter_update)
        return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:

        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_url func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "eplister"})
        chapters_list = chapter_list_container.find("a")
        newest_chapter_url = chapters_list["href"]
        return newest_chapter_url if newest_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_text func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "eplister"})
        chapters_list = chapter_list_container.find("a")
        newest_chapter = chapters_list.find("span", {"class": "chapternum"})
        newest_chapter_text = newest_chapter.text.replace("\n", " ").strip()
        return newest_chapter_text if newest_chapter_text else None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_div = soup.find("div", {"class": "imptdt"})
        status = status_div.find("i").text.strip()
        return status.lower() == "completed" or status.lower() == "dropped"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_human_name func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1", {"class": "entry-title"})
        return title_tag.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.asurascans_url.search(manga_url).group(1)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            raise MangaNotFoundError(manga_url=manga_url)

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)


class Aquamanga(ABCScan):
    base_url = "https://aquamanga.com/"
    fmt_url = base_url + "read/{manga_url_name}"
    name = "aquamanga"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        content = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not content or "Ray ID" in content:
            return await cls.report_error(
                bot, Exception("Failed to run check_updates func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", content)
            )

        soup = BeautifulSoup(content, "html.parser")

        chapter_list_container = soup.find("div", {"class": "listing-chapters_wrap"})
        chapter_list = chapter_list_container.find_all("a")
        new_updates: list[ChapterUpdate] = []

        for chapter in chapter_list:
            chapter_url = chapter["href"]
            chapter_text = chapter.text.strip()

            if chapter_url == last_chapter_url:
                break
            new_chapter_update = ChapterUpdate(
                chapter_url,
                chapter_text,
                cls._bs_is_series_completed(soup),
            )
            new_updates.append(new_chapter_update)
        return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:

        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_url func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "listing-chapters_wrap"})
        newest_chapter = chapter_list_container.find("a")
        newest_chapter_url = newest_chapter["href"]
        return newest_chapter_url

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_text func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("div", {"class": "listing-chapters_wrap"})
        chapters_list = chapter_list_container.find_all("a")
        newest_chapter = chapters_list[0]
        newest_chapter_text = newest_chapter.text.strip()
        return newest_chapter_text if newest_chapter_text else None

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
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_human_name func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        title_container = soup.find("div", {"class": "post-title"})
        title = title_container.find("h1")
        return title.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return super().get_manga_id(manga_url)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            raise MangaNotFoundError(manga_url=manga_url)

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)


class ReaperScans(ABCScan):
    base_url = "https://reaperscans.com/"
    fmt_url = base_url + "comics/{manga_id}-{manga_url_name}"
    name = "reaperscans"

    @staticmethod
    def _create_chapter_embed(img_url: str, human_name: str, chapter_url: str, chapter_text: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"{human_name} - {chapter_text}",
            url=chapter_url)
        embed.set_author(name="Reaper Scans")
        embed.description = f"Read {human_name} online for free on Reaper Scans!"
        embed.set_image(url=img_url)
        return embed

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        content = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not content or "Ray ID" in content:
            return await cls.report_error(
                bot, Exception("Failed to run check_updates func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", content)
            )

        soup = BeautifulSoup(content, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})
        chapter_list = chapter_list_container.find_all("a")
        new_updates: list[ChapterUpdate] = []

        # Get the image URL and alt text (aka the manga title) for the Embed
        img_container = soup.find("main", {"class": "mb-auto"})
        img = img_container.find("img")
        img_url = img["src"]
        img_alt = img["alt"]

        for chapter in chapter_list:
            chapter_url = chapter["href"]
            chapter_text = chapter.find("p").text.strip()

            if chapter_url == last_chapter_url:
                break
            new_chapter_update = ChapterUpdate(
                chapter_url,
                chapter_text,
                cls._bs_is_series_completed(soup),
                embed=cls._create_chapter_embed(
                    img_url, img_alt, chapter_url, chapter_text
                )
            )
            new_updates.append(new_chapter_update)
        return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:

        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_url func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})
        newest_chapter = chapter_list_container.find("a")
        newest_chapter_url = newest_chapter["href"]
        return newest_chapter_url if newest_chapter_url else None

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_curr_chapter_text func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        chapter_list_container = soup.find("ul", {"role": "list"})
        chapters_list = chapter_list_container.find_all("a")
        newest_chapter = chapters_list[0]
        newest_chapter_text = newest_chapter.find("p").text.strip()
        return newest_chapter_text if newest_chapter_text else None

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("dl", {"class": "mt-2"})
        _type, content = status_container.find_all("dd"), status_container.find_all("dt")
        for _type_element, content_element in zip(_type, content):
            if content_element.text.strip().lower() == "source status":
                status = _type_element.text.strip()
                return status.lower() == "completed" or status.lower() == "dropped"
        else:
            raise Exception("Failed to find source status.")

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            return await cls.report_error(
                bot, Exception("Failed to run get_human_name func. Status: N/A"),
                file=write_to_discord_file(cls.name + ".html", text)
            )

        soup = BeautifulSoup(text, "html.parser")
        title_tag = soup.find("h1")
        return title_tag.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return RegExpressions.reaperscans_url.search(manga_url).group(1)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        text = await bot.cf_scraper.bypass_cloudflare(manga_url)
        if not text or "Ray ID" in text:
            raise MangaNotFoundError(manga_url=manga_url)

        soup = BeautifulSoup(text, "html.parser")
        return cls._bs_is_series_completed(soup)


class AniglisScans(ABCScan):
    base_url = "https://anigliscans.com/"
    fmt_url = base_url + "series/{manga_url_name}"
    name = "aniglisscans"

    @classmethod
    async def check_updates(
            cls,
            bot: MangaClient,
            human_name: str,
            manga_url: str,
            manga_id: str,
            last_chapter_url: str,
    ) -> list[ChapterUpdate] | None:

        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run check_updates func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find("div", {"class": "eplister"})
            chapter_list = chapter_list_container.find_all("a")
            new_updates: list[ChapterUpdate] = []

            for chapter in chapter_list:
                chapter_url = chapter["href"]

                chapter_text = chapter.find("span", {"class": "chapternum"}).text
                chapter_text = chapter_text.replace("\n", " ").strip()

                if last_chapter_url == chapter_url:
                    break

                new_chapter_update = ChapterUpdate(
                    chapter_url,
                    chapter_text,
                    cls._bs_is_series_completed(soup),
                )
                new_updates.append(new_chapter_update)
            return list(reversed(new_updates))

    @classmethod
    async def get_curr_chapter_url(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:

        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_url func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find("div", {"class": "eplister"})
            newest_chapter = chapter_list_container.find("a")
            newest_chapter_url = newest_chapter["href"]
            return newest_chapter_url

    @classmethod
    async def get_curr_chapter_text(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_curr_chapter_text func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")

            chapter_list_container = soup.find("div", {"class": "eplister"})
            newest_chapter = chapter_list_container.find("a")
            newest_chapter_text = newest_chapter.find("span", {"class": "chapternum"}).text
            newest_chapter_text = newest_chapter_text.replace("\n", " ").strip()
            return newest_chapter_text

    @classmethod
    def _bs_is_series_completed(cls, soup: BeautifulSoup) -> bool:
        """Returns whether the series is completed or not."""
        status_container = soup.find("div", {"class": "tsinfo"})
        status_tag = status_container.find("div", {"class": "imptdt"})
        status = status_tag.find("i").text.strip().lower()
        return status == "completed" or status == "dropped"

    @classmethod
    async def get_human_name(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> str | None:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                return await cls.report_error(
                    bot, Exception("Failed to run get_human_name func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )

            soup = BeautifulSoup(await resp.text(), "html.parser")
            title_tag = soup.find("h1", {"class": "entry-title"})
            return title_tag.text.strip()

    @classmethod
    def get_manga_id(cls, manga_url: str) -> str:
        return super().get_manga_id(manga_url)

    @classmethod
    async def is_series_completed(
            cls, bot: MangaClient, manga_id: str, manga_url: str
    ) -> bool:
        async with bot.session.get(manga_url) as resp:
            if resp.status != 200:
                await cls.report_error(
                    bot, Exception("Failed to run is_series_completed func. Status: " + str(resp.status)
                                   ),
                    file=write_to_discord_file(cls.name + ".html", await resp.text())
                )
                return False

            soup = BeautifulSoup(await resp.text(), "html.parser")
            return cls._bs_is_series_completed(soup)


SCANLATORS: dict[str, ABCScan] = {
    Toonily.name: Toonily,
    TritiniaScans.name: TritiniaScans,
    Manganato.name: Manganato,
    MangaDex.name: MangaDex,
    FlameScans.name: FlameScans,
    AsuraScans.name: AsuraScans,
    Aquamanga.name: Aquamanga,
    ReaperScans.name: ReaperScans,
    AniglisScans.name: AniglisScans,
}
