from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Dict

import aiosqlite
from fuzzywuzzy import fuzz

if TYPE_CHECKING:
    from .bot import MangaClient

from src.core.objects import GuildSettings, Manga
from io import BytesIO
import pandas as pd
import sqlite3
from json import loads, dumps


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
                    last_chapter_url INT NOT NULL,
                    last_chapter_string TEXT NOT NULL,
                    completed BOOLEAN NOT NULL DEFAULT false,
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    UNIQUE(id) ON CONFLICT IGNORE
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
                    updates_role_id INTEGER DEFAULT NULL,
                    webhook_url TEXT NOT NULL,
                    UNIQUE (guild_id) ON CONFLICT IGNORE
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS cookies (
                    scanlator TEXT PRIMARY KEY NOT NULL,
                    cookie TEXT NOT NULL,
                    FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                    UNIQUE (scanlator) ON CONFLICT REPLACE
                )
                """
            )
            await db.commit()

    def export(self) -> BytesIO:
        """As this function carries out non-async operations, it must be run in a thread executor."""

        with sqlite3.connect(self.db_name) as conn:
            output = BytesIO()
            writer = pd.ExcelWriter(output, engine="openpyxl")

            # Get all tables
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [table[0] for table in cursor.fetchall()]
            schemas = []

            for table in tables:
                df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                for col in df.columns:
                    if df[col].dtype == 'int64':  # convert int64 columns to string
                        df[col] = df[col].astype(str)
                df.to_excel(writer, sheet_name=table, index=False)

                # Export table schema
                schema = pd.read_sql_query(f"PRAGMA table_info({table})", conn)
                schemas.append((table, schema))

            for table, schema in schemas:
                schema.to_excel(writer, sheet_name=f"{table} _schema_", index=False)

            writer.book.save(output)
            output.seek(0)
            return output

    def import_data(self, file: BytesIO) -> None:
        """Imports data from an Excel file into the database."""

        with sqlite3.connect(self.db_name) as conn:
            # Read the Excel file into a dictionary of DataFrames
            dfs = pd.read_excel(file, sheet_name=None)

            # Import each table and its schema
            for table_name, df in dfs.items():
                if table_name.endswith(" _schema_"):
                    continue  # Skip schema tables
                    # Import table schema
                    # df.to_sql(table_name[:-9], conn, index=False, if_exists="replace")
                else:
                    # Import table data
                    df.to_sql(table_name, conn, index=False, if_exists="append")

    async def add_series(self, manga_obj: Manga) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO series (id, human_name, manga_url, last_chapter_url, last_chapter_string, completed, 
                scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT(id) DO NOTHING;
                """,
                (manga_obj.to_tuple()),
            )

            await db.commit()

    async def set_cookie(self, scanlator: str, cookie: List[Dict]) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            serialized_cookies = dumps(cookie)
            await db.execute(
                """
                INSERT INTO cookies (scanlator, cookie) VALUES ($1, $2)
                """,
                (scanlator, serialized_cookies),
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
                INSERT INTO config (guild_id, channel_id, updates_role_id, webhook_url) VALUES ($1, $2, $3, $4
                ) ON CONFLICT(guild_id) DO UPDATE SET channel_id = $2, updates_role_id = $3, webhook_url = $4 
                WHERE guild_id = $1;
                """,
                settings.to_tuple(),
            )

            await db.commit()

    async def get_cookie(self, scanlator: str):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT cookie FROM cookies WHERE scanlator = $1;
                """,
                (scanlator,),
            )
            cookie = await cursor.fetchone()
            if cookie is not None:
                return loads(cookie[0])

    # noinspection PyUnresolvedReferences
    async def get_user_subs(self, user_id: int, current: str = None) -> list[Manga]:
        """
        Returns a list of Manga class objects each representing a manga the user is subscribed to.
        >>> [Manga, ...]
        >>> None if no manga is found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            await db.create_function("levenshtein", 2, _levenshtein_distance)
            if current is not None:
                query = """
                        SELECT * FROM series WHERE series.id IN (SELECT series_id FROM users WHERE id = $1
                        ) 
                        ORDER BY levenshtein(human_name, $2) DESC
                        LIMIT 25;
                        """
                params = (user_id, current)

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

    async def get_guild_config(self, guild_id: int) -> GuildSettings | None:
        """
        Returns:
             Optional[GuildSettings] object if a config is found for the guild.
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
        >>> [Manga, ...)]
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
        >>> [Manga, ...)]
        """
        if current is not None:
            async with aiosqlite.connect(self.db_name) as db:
                await db.create_function("levenshtein", 2, _levenshtein_distance)

                async with db.execute(
                    """
                    SELECT * FROM series
                    ORDER BY levenshtein(human_name, ?) DESC
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
            result = await db.execute(
                """
                UPDATE series SET last_chapter_url = $1, last_chapter_string = $2 WHERE id = $3;
                """,
                (manga.last_chapter_url, manga.last_chapter_string, manga.id),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {manga.id} was found.")
            await db.commit()

    async def delete_cookie(self, scanlator: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM cookies WHERE scanlator = ?;
                """,
                (scanlator,),
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
        self, series_ids: list[str] | tuple[str] | set[str]
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            id_list = ",".join([f"'{_id}'" for _id in series_ids])
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

    async def get_webhooks(self) -> set[str]:
        """
        Returns a set of all webhook URLs in the config table.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                """
                SELECT webhook_url FROM config;
                """
            ) as cursor:
                return set([url for url, in await cursor.fetchall()])
