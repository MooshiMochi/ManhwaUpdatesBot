from __future__ import annotations

import os
from typing import TYPE_CHECKING

import aiosqlite
from fuzzywuzzy import fuzz

if TYPE_CHECKING:
    from core.bot import MangaClient

from src.objects import GuildSettings, Manga


def _levenshtein_distance(a: str, b: str) -> int:
    return fuzz.ratio(a, b)


class Database:
    def __init__(self, client: MangaClient, database_name: str = "database.db"):
        self.client: MangaClient = client
        self.db_name = database_name

        if not os.path.exists(f"./{self.db_name}"):
            with open(self.db_name, "w") as _:
                ...

    async def async_init(self) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS series (
                    id TEXT PRIMARY KEY NOT NULL,
                    human_name TEXT NOT NULL,
                    manga_url TEXT NOT NULL,
                    last_chapter FLOAT NOT NULL,
                    completed BOOLEAN NOT NULL DEFAULT false,
                    scanlator TEXT NOT NULL DEFAULT 'Unknown'
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (guild_id) REFERENCES config (guild_id),
                    UNIQUE (id, series_id, guild_id) ON CONFLICT IGNORE
                )
                """
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS config (
                    guild_id INTEGER PRIMARY KEY NOT NULL,
                    channel_id INTEGER NOT NULL,
                    updates_role_id INTEGER NOT NULL,
                    webhook_url TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def add_series(self, manga_obj: Manga) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            print(manga_obj.to_tuple())
            await db.execute(
                """
                INSERT INTO series (id, human_name, manga_url, last_chapter, completed, scanlator) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT(id) DO NOTHING;
                """,
                (manga_obj.to_tuple()),
            )

            await db.commit()

    async def subscribe_user(self, user_id: int, guild_id: int, series_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO users (id, series_id, guild_id) VALUES ($1, $2, $3);
                """,
                (user_id, series_id, guild_id),
            )

            await db.commit()

    async def upsert_config(self, settings: GuildSettings) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO config (guild_id, channel_id, updates_role_id, webhook_url) VALUES ($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_id = $2, updates_role_id = $3, webhook_url = $4 WHERE guild_id = $1;
                """,
                settings.to_tuple(),
            )

            await db.commit()

    async def get_user_subs(self, user_id: int, current: str = None) -> list[Manga]:
        async with aiosqlite.connect(self.db_name) as db:
            """
            Returns a list of Manga class objects each representing a manga the user is subscribed to.
            >>> [manga: Manga, ...]
            >>> None if no manga is found.
            """

            if current is not None:
                query = """
                        SELECT * FROM series WHERE series.id IN (SELECT series_id FROM users WHERE id = ?) AND series.human_name LIKE ? LIMIT 25;
                        """
                params = (user_id, f"%{current}%")

            else:
                query = """
                        SELECT * FROM series WHERE series.id IN (SELECT series_id FROM users WHERE id = ?);
                        """
                params = (user_id,)

            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    return Manga.from_tuples(result)
                return []

    async def get_guild_config(self, guild_id: int) -> tuple:
        """
        Returns a GuildSettings object.
        >>> GuildSettings(guild_id, channel_id, updates_role_id, webhook_url)
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM config WHERE guild_id = ?;
                """,
                (guild_id,),
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    return GuildSettings(self.client, *result)

    async def get_series(self, series_id: str) -> Manga | None:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM series WHERE id = ?;
                """,
                (series_id,),
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    return Manga(*result)

    async def get_all_series(self) -> list[Manga] | None:
        """
        Returns a list of Manga objects containing all series in the database.
        >>> [manga_obj, ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM series;
                """
            ) as cursor:
                if result := await cursor.fetchall():
                    return Manga.from_tuples(result)

    async def _get_all_series_autocomplete(self, current: str = None) -> list:
        """
        Returns a list of Manga objects containing all series in the database.
        >>> [manga_obj, ...)]
        """
        if current is not None:
            async with aiosqlite.connect(self.db_name) as db:
                await db.create_function("levenshtein", 2, _levenshtein_distance)

                async with db.execute(
                    """
                    SELECT * FROM series
                    ORDER BY levenshtein(human_name, ?)
                    LIMIT 25;
                    """,
                    (current,),
                ) as cursor:
                    if result := await cursor.fetchall():
                        return Manga.from_tuples(result)
        else:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute(
                    """
                    SELECT * FROM series LIMIT 25;
                    """,
                ) as cursor:
                    if result := await cursor.fetchall():
                        return Manga.from_tuples(result)

    async def get_all_subscribed_series(self) -> list[Manga]:
        """
        Returns a list of tuples containing all series that are subscribed to by at least one user.
        >>> [Manga, ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM series WHERE series.id IN (
                    SELECT series_id FROM users
                );
                """
            ) as cursor:
                result = await cursor.fetchall()
                if not result:
                    return []
                else:
                    return Manga.from_tuples(result)

    async def update_series(self, manga: Manga) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            new_chapter = float(new_chapter)
            result = await db.execute(
                """
                UPDATE series SET last_chapter = ? WHERE id = ?;
                """,
                (manga.last_chapter, manga.id),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {manga.id} was found.")
            await db.commit()

    async def delete_series(self, series_id: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM series WHERE id = ?;
                """,
                (series_id,),
            )

            await db.commit()

    async def unsub_user(self, user_id: int, series_id: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM users WHERE id = ? and series_id = ?;
                """,
                (user_id, series_id),
            )

            await db.commit()

    async def delete_config(self, guild_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM config WHERE guild_id = ?;
                """,
                (guild_id,),
            )

            await db.commit()

    async def bulk_delete_series(
        self, series: list[Manga] | tuple[Manga] | set[Manga]
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            id_list = ",".join([f"'{manga.id}'" for manga in series])
            await db.execute(
                f"""
                DELETE FROM series WHERE id IN ({id_list});
                """
            )
            await db.commit()

    async def get_series_webhook_role_pairs(self) -> list[tuple[str, str, int]]:
        """

        Returns: [(series_id, webhook_url, updates_role_id), ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT series.id, config.webhook_url, config.updates_role_id FROM series
                INNER JOIN config ON series.id IN (
                    SELECT series_id FROM users WHERE guild_id = config.guild_id
                );
                """
            ) as cursor:
                return await cursor.fetchall()
