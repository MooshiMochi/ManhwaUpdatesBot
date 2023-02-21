import urllib.parse

import aiohttp
from bs4 import BeautifulSoup


class MangaUpdates:
    @staticmethod
    async def scrape_series_id(
        session: aiohttp.ClientSession, manga_title: str
    ) -> tuple[str, str, str] | None:
        """Scrape the series ID from MangaUpdates.com

        Returns:
            >>> (name, url, _id)
            >>> None if not found
        """
        encoded_title = urllib.parse.quote(manga_title)
        async with session.get(
            f"https://www.mangaupdates.com/search.html?search={encoded_title}"
        ) as resp:
            if resp.status != 200:
                return None

            soup = BeautifulSoup(await resp.text(), "html.parser")

            series_info = soup.find("div", {"class": "col-6 py-1 py-md-0 text"})
            first_title = series_info.find("a")
            name = first_title.text
            url = first_title["href"]
            _id = url.split("/")[-2]
            if len(id) >= 3:
                return name, url, _id
            return None

    @staticmethod
    async def is_series_completed(
        session: aiohttp.ClientSession, manga_id: str
    ) -> bool:
        """Check if the series is completed or not."""
        api_url = "https://api.mangaupdates.com/v1/series/{id}"

        async with session.get(api_url.format(id=manga_id)) as resp:
            if resp.status != 200:
                return None

            data = await resp.json()
            return data["completed"]
