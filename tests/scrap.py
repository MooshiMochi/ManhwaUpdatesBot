from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.scanlators.classes import BasicScanlator

if TYPE_CHECKING:
    from src.core import MangaClient

from discord.ext import commands
from src.core.objects import Manga
from src.core.scanlators import scanlators

# Checklist:
#
done = [
    "tritinia",
    # "manganato",
    # "toonily",
    # "mangadex",
    # "flamecomics",
    # "asura",
    # "reaperscans",
    # "comick",
    # "drakescans",
    # "nitroscans",
    # "mangapill",
    # "bato",
    # "omegascans",
]


class FixDbCog(commands.Cog):
    def __init__(self, bot: "MangaClient"):
        self.bot = bot

    async def delete_from_db(self, _id: str, scanlator: str):
        await self.bot.db.execute(
            "DELETE FROM series WHERE id = $1 AND scanlator = $2",
            _id, scanlator
        )
        await self.bot.db.execute(
            "DELETE FROM bookmarks WHERE series_id = $1 AND scanlator = $2",
            _id, scanlator
        )
        await self.bot.db.execute(
            "DELETE FROM user_subs WHERE series_id = $1 AND scanlator = $2",
            _id, scanlator
        )
        await self.bot.db.execute(
            "DELETE FROM tracked_guild_series WHERE series_id = $1 AND scanlator = $2",
            _id, scanlator
        )

    async def replace_series_id(self, old_id: str, new_id: str, scanlator: str, delete_old: bool = False):
        await self.bot.db.execute(
            "UPDATE bookmarks SET series_id = $1 WHERE series_id = $2 AND scanlator = $3",
            new_id, old_id, scanlator
        )
        await self.bot.db.execute(
            "UPDATE user_subs SET series_id = $1 WHERE series_id = $2 AND scanlator = $3",
            new_id, old_id, scanlator
        )
        await self.bot.db.execute(
            "UPDATE tracked_guild_series SET series_id = $1 WHERE series_id = $2 AND scanlator = $3",
            new_id, old_id, scanlator
        )
        if delete_old:
            await self.bot.db.execute(
                "DELETE FROM series WHERE id = $1 AND scanlator = $2",
                old_id, scanlator
            )

    async def insert_to_db(self, manga: Manga):
        await self.bot.db.execute(
            f"""INSERT INTO series (id, title, url, synopsis, series_cover_url, last_chapter, available_chapters, 
            status, scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT(id, scanlator) DO UPDATE SET url=$3, series_cover_url = $5, last_chapter = $6, available_chapters = $7;"""
            , *manga.to_tuple()
        )

    async def get_raw_manga_obj(self, _id: str, scanlator: str):
        result = await self.bot.db.execute(
            "SELECT * FROM main.series WHERE id = $1 AND scanlator = $2",
            _id, scanlator
        )
        return Manga.from_tuple(result[0])

    async def get_raw_scanaltor_manga_objs(self, scanlator: str):
        mangas = []
        result = await self.bot.db.execute(
            "SELECT * FROM main.series WHERE scanlator = $1",
            scanlator
        )
        for row in result:
            mangas.append(Manga.from_tuple(row))
        return mangas

    async def enable_all_scanlators(self):
        await self.bot.db.execute("UPDATE main.scanlators_config SET enabled = TRUE")
        for sc in self.bot._all_scanners:
            if sc not in scanlators:
                scanlators[sc] = self.bot._all_scanners[sc]

    async def delete_old_scan_configs(self):
        deleted_scanlators = 0
        configs = await self.bot.db.execute("SELECT scanlator from main.scanlators_config")
        for config in configs:
            c = config[0]
            if c not in self.bot._all_scanners:
                await self.bot.db.execute("DELETE FROM main.scanlators_config WHERE scanlator = $1", c)
                deleted_scanlators += 1
        print(f"Deleted {deleted_scanlators} old scanlators from the database.")

    async def cog_load(self) -> None:
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        # await self.check_invalid_website_formats()
        await self.fix_manganaot()
        # await self.delete_old_scan_configs()
        # await self.enable_all_scanlators()

    async def check_invalid_website_formats(self):
        print("Checking for invalid URLs")
        all_series = await self.bot.db.get_all_series()
        series = {}
        to_fix = set()
        for item in all_series:
            if item.scanlator not in series:
                series[item.scanlator] = []
            series[item.scanlator].append(item)

        for name in self.bot._all_scanners:
            print(f"Checking {name}")
            # mangas = await self.bot.db.get_all_series(scanlator=sc_name)
            mangas = series.get(name)
            if not mangas:
                continue
            sc: BasicScanlator = self.bot._all_scanners[name]
            for m in mangas:
                if not sc.json_tree.rx.match(m.url):
                    print(f"Invalid URL found for {name}: {m.url} (ID: {m.id})")
                    to_fix.add(name)
                    break
            print(f"Finished checking {name}")

        print(to_fix)
        print("Finished checking for invalid URLs")

    async def check_sinlge_manga_for_invalid_website(self, manga: Manga, scanlator: BasicScanlator):
        if not scanlator.json_tree.rx.match(manga.url):
            print(f"Invalid URL found for {scanlator.name}: {manga.url} (ID: {manga.id})")
            return False
        return True

    async def fix_manganaot(self):
        scanlator = scanlators.get("manganato")
        if not scanlator:
            print("Manganato scanlator not found!")
            return

        mangas: list[Manga] = await self.get_raw_scanaltor_manga_objs("manganato")
        for entry in mangas:
            title = entry.title
            # search for the manga by title, and check if any of the titles within the 1st 3 entries match 100% (lower)
            # if they do, then get the manga object for the found manga, add it to the db, then delete the old one
            # and replace the old ID to the new ID in all relevant tables
            search_results = await scanlator.search(title)
            correct_manga = None
            for result in search_results[:3]:
                if result.title.lower() == title.lower():
                    correct_manga = result
                    break
            else:
                print(f"No exact match found for {title}")
                continue
            if correct_manga:
                correct_id = correct_manga.id
                if correct_id != entry.id:
                    print(f"Fixing manga ID for {title}: {entry.id} -> {correct_id}")
                    # Check if the correct ID already exists
                    existing = await self.get_raw_manga_obj(correct_id, "manganato")
                    if existing:
                        print(f"Correct ID {correct_id} already exists. Merging data.")
                        await self.replace_series_id(entry.id, correct_id, "manganato", delete_old=True)
                    else:
                        print(f"Inserting manga with correct ID {correct_id}.")
                        entry.id = correct_id
                        await self.insert_to_db(entry)
                        await self.delete_from_db(entry.id, "manganato")
                success = await self.check_sinlge_manga_for_invalid_website(correct_manga, scanlator)
                if success:
                    print(f"Successfully fixed manga: {title}")
                else:
                    print(f"Failed to fix manga: {title}")


async def setup(bot: "MangaClient"):
    await bot.add_cog(FixDbCog(bot))
