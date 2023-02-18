from __future__ import annotations

import os
from typing import TYPE_CHECKING, Self

import aiosqlite

if TYPE_CHECKING:
    from core.bot import MangaClient


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
                    updates_role_id INTEGER NOT NULL
                )
                """
            )

            await db.commit()

    async def add_series(
        self,
        series_id: str,
        human_name: str,
        series_url: str,
        last_chapter: float,
        completed: bool,
        scanlator: str,
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO series (id, human_name, manga_url, last_chapter, completed, scanlator) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT(id) DO NOTHING;
                """,
                (series_id, human_name, series_url, last_chapter, completed, scanlator),
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

    async def add_config(
        self, guild_id: int, channel_id: int, updates_role_id: int
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO config (guild_id, channel_id, updates_role_id) VALUES ($1, $2, $3) ON CONFLICT(guild_id) DO UPDATE SET channel_id = $2, updates_role_id = $3 WHERE guild_id = $1;
                """,
                (guild_id, channel_id, updates_role_id),
            )

            await db.commit()

    async def get_series(self, name: str) -> tuple:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM series WHERE name = ?;
                """,
                (name,),
            ) as cursor:
                return await cursor.fetchone()

    async def get_user_subs(self, user_id: int, current: str = None) -> tuple:
        async with aiosqlite.connect(self.db_name) as db:
            """
            Returns a tuple of tuples containing the user's series_id and their name.
            >>> ((series_id, human_name, last_chapter), ...)
            """

            if current is not None:
                async with db.execute(
                    """
                    SELECT series.id, series.human_name, series.last_chapter FROM series WHERE series.id IN (
                        SELECT series_id FROM users WHERE id = ?
                    ) AND series.human_name LIKE ?;
                    """,
                    (user_id, f"%{current}%"),
                ) as cursor:
                    return await cursor.fetchall()

            async with db.execute(
                """
                SELECT series.id, series.human_name, series.last_chapter FROM series WHERE series.id IN (
                    SELECT series_id FROM users WHERE id = ?
                );              
                """,
                (user_id,),
            ) as cursor:
                return await cursor.fetchall()

    async def get_guild_config(self, guild_id: int) -> tuple:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT channel_id, updates_role_id FROM config WHERE guild_id = ?;
                """,
                (guild_id,),
            ) as cursor:
                return await cursor.fetchone()

    async def get_series_name(self, series_id: str) -> str | None:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT human_name FROM series WHERE id = ?;
                """,
                (series_id,),
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None

    async def get_series_channels_and_roles(self, series_id: int) -> list:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT channel_id, updates_role_id FROM config WHERE guild_id IN (
                    SELECT guild_id FROM users WHERE series_id = ?
                );
                """,
                (series_id,),
            ) as cursor:
                return await cursor.fetchall()

    async def get_all_series(self) -> list:
        """
        Returns a list of tuples containing all series in the database.
        >>> [(id, human_name, manga_url, last_chapter, completed, scanlator), ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM series;
                """
            ) as cursor:
                return await cursor.fetchall()

    async def get_all_user_subs(self) -> list:
        """
        Returns a dict of user_id: list[series_id] containing all the series all users are subscribed to.
        >>> {user_id: [series_id, ...], ...}
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT * FROM users;
                """
            ) as cursor:
                result: list[tuple[int, str]] = await cursor.fetchall()
                results_dict: dict[int, list[str]] = {}

                for tup in result:
                    user_id = tup[0]
                    if user_id not in results_dict:
                        results_dict[user_id] = []
                    results_dict[user_id].append(tup[1])

                return results_dict

    async def update_series(self, series_id: str, new_chapter: float) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            new_chapter = float(new_chapter)
            result = await db.execute(
                """
                UPDATE series SET last_chapter = ? WHERE id = ?;
                """,
                (new_chapter, series_id),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {series_id} was found.")
            await db.commit()

    async def update_config(
        self, guild_id: int, channel_id: int, updates_role_id: int
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                UPDATE config SET channel_id = ?, updates_role_id = ? WHERE guild_id = ?;
                """,
                (channel_id, updates_role_id, guild_id),
            )

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
        self, series_ids: tuple[str] | list[str] | set[str]
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            id_list = ",".join([f"'{id}'" for id in series_ids])
            await db.execute(
                f"""
                DELETE FROM series WHERE id IN ({id_list});
                """
            )
            await db.commit()

    async def delete_all_series(self) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM series;
                """
            )

            await db.commit()

    async def delete_all_users(self) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM users;
                """
            )

            await db.commit()

    async def delete_all_config(self) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM config;
                """
            )

            await db.commit()
