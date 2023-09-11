from __future__ import annotations

import os
from datetime import datetime
from typing import Any, List, TYPE_CHECKING

import aiosqlite
import discord
from fuzzywuzzy import fuzz

if TYPE_CHECKING:
    from .bot import MangaClient

from src.core.objects import GuildSettings, Manga, Bookmark, Chapter
from src.core.scanners import SCANLATORS
from io import BytesIO
import pandas as pd
import sqlite3
from src.core.errors import CustomError, DatabaseError


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
                    url TEXT NOT NULL,
                    synopsis TEXT,
                    series_cover_url TEXT NOT NULL,
                    last_chapter TEXT,
                    available_chapters TEXT,
                    
                    completed BOOLEAN NOT NULL DEFAULT false,
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    UNIQUE(id) ON CONFLICT IGNORE
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_subs (
                    id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    UNIQUE (id, series_id) ON CONFLICT IGNORE
                )
                """
            )

            await db.execute(
                # user_id: the discord ID of the user the bookmark belongs to
                # series_id: the ID of the series from the series table
                # last_read_chapter_index: the last chapter the user read
                # guild_id: the discord guild the user bookmarked the manga from
                # last_updated_ts: the timestamp of the last time the bookmark was updated by the user
                # user_created: whether the bookmark was created by the user or by the bot
                """
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    last_read_chapter_index TEXT DEFAULT NULL,
                    guild_id INTEGER NOT NULL,
                    last_updated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_created BOOLEAN NOT NULL DEFAULT false,
                    
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (user_id) REFERENCES user_subs (id),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    UNIQUE (user_id, series_id) ON CONFLICT IGNORE
                    )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY NOT NULL,             
                    notifications_channel_id INTEGER,
                    default_ping_role_id INTEGER DEFAULT NULL,
                    notifications_webhook TEXT NOT NULL,
                    auto_create_role BOOLEAN NOT NULL DEFAULT false,
                    dev_notifications_ping BOOLEAN NOT NULL DEFAULT true,
                    UNIQUE (guild_id) ON CONFLICT IGNORE
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_guild_series (
                    guild_id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    role_id INTEGER,
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    UNIQUE (guild_id, series_id) ON CONFLICT REPLACE
                );
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scanlators_config (
                    scanlator TEXT PRIMARY KEY NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1
                );
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_created_roles (
                    guild_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    UNIQUE (guild_id, role_id) ON CONFLICT REPLACE
                );
                """
                # FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id)
            )
            await db.commit()

    async def execute(self, query: str, *args) -> Any:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(query, args) as cursor:
                result = await cursor.fetchall()
                await db.commit()
                return result

    def export(self, raw: bool = False) -> BytesIO:
        """As this function carries out non-async operations, it must be run in a thread executor."""
        if raw is True:
            with open(self.db_name, "rb") as f:
                return BytesIO(f.read())

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

    async def toggle_scanlator(self, scanlator: str) -> None:
        """
        Summary: Toggles a scanlator's enabled status.

        Parameters:
            scanlator (str): The scanlator to toggle.

        Returns:
            (bool): Whether the scanlator was enabled or disabled.
        """
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO scanlators_config (scanlator, enabled) VALUES ($1, 0)
                ON CONFLICT(scanlator) DO UPDATE SET enabled = NOT enabled;
                """,
                # as scanlators are enabled by default, we will insert 0 when first toggling
                (scanlator,),
            )
            cursor = await db.execute(
                """
                SELECT enabled FROM scanlators_config WHERE scanlator = $1;
                """,
                (scanlator,),
            )
            result = await cursor.fetchone()
            await db.commit()
            return result[0]

    async def get_disabled_scanlators(self) -> List[str]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT scanlator FROM scanlators_config WHERE enabled = 0;
                """
            )
            result = await cursor.fetchall()
            await db.commit()
            return [row[0] for row in result]

    async def add_series(self, manga_obj: Manga) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            if manga_obj.scanlator in SCANLATORS:
                await db.execute(
                    """
                INSERT INTO series (id, human_name, url, synopsis, series_cover_url, last_chapter, available_chapters, 
                completed, scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id) DO NOTHING;
                    """,
                    (SCANLATORS[manga_obj.scanlator].unload_manga_objects([manga_obj])[0].to_tuple()),
                )

                await db.commit()
            else:
                raise CustomError(
                    f"[{manga_obj.scanlator.title()}] is currently disabled.\nThis action cannot be completed."
                )

    async def upsert_bookmark(self, bookmark: Bookmark) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            if bookmark.manga.scanlator in SCANLATORS:
                await db.execute(
                    """
                INSERT INTO series (id, human_name, url, synopsis, series_cover_url, last_chapter, available_chapters, 
                completed, scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id) DO NOTHING;
                    """,
                    (SCANLATORS[bookmark.manga.scanlator].unload_manga_objects([bookmark.manga])[0].to_tuple()),
                )
            else:
                raise CustomError(
                    f"[{bookmark.manga.scanlator.title()}] is currently disabled.\nThis action cannot be completed."
                )

            await db.execute(
                """
                INSERT INTO bookmarks (
                    user_id,
                    series_id,
                    last_read_chapter_index,
                    guild_id,
                    last_updated_ts,
                    user_created
                    ) 
                VALUES ($1, $2, $3, $4, $5, $6) 
                ON CONFLICT(user_id, series_id) DO 
                UPDATE SET last_read_chapter_index=$3, last_updated_ts=$5, user_created=$6;
                """,
                (bookmark.to_tuple()),
            )
            await db.commit()
            return True

    async def subscribe_user(self, user_id: int, guild_id: int, series_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            # INSERT OR IGNORE INTO user_subs (id, series_id, guild_id) VALUES ($1, $2, $3);
            await db.execute(
                """
                INSERT INTO user_subs (id, series_id, guild_id) 
                VALUES ($1, $2, $3) 
                ON CONFLICT(id, series_id) DO NOTHING;
                """,
                (user_id, series_id, guild_id),
            )

            await db.commit()

    async def is_user_subscribed(self, user_id: int, manga_id: Any) -> bool:
        """
        Summary: Checks if a user is subscribed to a manga.

        Args:
            user_id: The user's ID.
            manga_id: The manga's ID.

        Returns:
            (bool): Whether the user is subscribed to the manga.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT * FROM user_subs WHERE id = $1 AND series_id = $2;
                """,
                (user_id, manga_id),
            )
            result = await cursor.fetchone()
            return result is not None

    async def mark_chapter_read(self, user_id: int, guild_id: int, manga: Manga, chapter: Chapter) -> bool:
        """
        Summary: Marks a chapter as read for a user.

        Args:
            user_id: The user's ID.
            guild_id: The guild's ID.
            manga: The manga object.
            chapter: The chapter object.

        Returns:
            (bool): Whether the chapter was marked as read.
        """
        async with aiosqlite.connect(self.db_name) as db:
            result = await db.execute(
                """
                INSERT INTO bookmarks (
                    user_id, series_id, last_read_chapter_index, guild_id, last_updated_ts, user_created
                    ) 
                VALUES ($1, $2, $3, $4, $5, false) 
                ON CONFLICT(user_id, series_id) 
                DO UPDATE SET last_read_chapter_index = $3, last_updated_ts = $5;
                """,
                (user_id, manga.id, chapter.to_json(), guild_id, datetime.now()),
            )
            if result.rowcount < 1:
                raise DatabaseError("Failed to mark chapter as read.")
            await db.commit()
            return True

    async def upsert_config(self, settings: GuildSettings) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO guild_config (
                    guild_id, notifications_channel_id, default_ping_role_id, 
                    notifications_webhook, auto_create_role, dev_notifications_ping
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT(guild_id) 
                DO UPDATE SET 
                    notifications_channel_id = $2, default_ping_role_id = $3, 
                    notifications_webhook = $4, auto_create_role = $5, dev_notifications_ping = $6
                WHERE guild_id = $1;
                """,
                settings.to_tuple(),
            )

            await db.commit()

    async def get_all_user_subs(self, user_id: int, current: str | None) -> list[Manga]:
        """
        Summary:
            Returns a list of Manga class objects each representing a manga the user is subscribed to.
        Args:
            user_id: The user's id.
            current: The current search query.

        Returns:
            List[Manga] if manga are found.
            None if no manga are found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
                SELECT
                    s.id,
                    s.human_name,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.completed,
                    s.scanlator
                    
                FROM series AS s
                INNER JOIN user_subs AS u
                ON s.id = u.series_id
                WHERE u.id = $1
                """
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                query += " ORDER BY levenshtein(human_name, $2) DESC LIMIT 25;"
                params = (user_id, current)
            else:
                query += ";"
                params = (user_id,)
            cursor = await db.execute(
                query,
                params,
            )
            result = await cursor.fetchall()
            if result:
                return Manga.from_tuples(result)  # noqa
            return []

    # noinspection PyUnresolvedReferences
    async def get_user_guild_subs(self, guild_id: int, user_id: int, current: str = None) -> list[Manga]:
        """
        Returns a list of Manga class objects each representing a manga the user is subscribed to.
        >>> [Manga, ...]
        >>> None if no manga is found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            SELECT * FROM series 
            WHERE series.id IN (
                SELECT series_id FROM user_subs WHERE guild_id = $1 AND id = $2
                )
            """
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                query += " ORDER BY levenshtein(human_name, $3) DESC LIMIT 25;"
                params = (guild_id, user_id, current)
            else:
                query += ";"
                params = (guild_id, user_id)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return []

    async def get_user_subs(self, user_id: int, current: str = None) -> list[Manga]:
        """
        Returns a list of Manga class objects each representing a manga the user is subscribed to.
        >>> [Manga, ...]
        >>> None # if no manga is found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            SELECT * FROM series 
            WHERE series.id IN (
                SELECT series_id FROM user_subs WHERE id = $1
                )
            """
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                query += " ORDER BY levenshtein(human_name, $2) DESC LIMIT 25;"
                params = (user_id, current)
            else:
                query += ";"
                params = (user_id,)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return []

    async def get_series_to_delete(self) -> list[Manga] | None:
        """
        Summary:
            Returns a list of Manga class objects that needs to be deleted.
            It needs to be deleted when:
                - no user is subscribed to the manga
                - no user has bookmarked the manga

        Returns:
            list[Manga] | None: list of Manga class objects that needs to be deleted.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM series WHERE series.id NOT IN (SELECT series_id FROM user_subs)
                    AND series.id NOT IN (SELECT series_id FROM bookmarks);
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return None

    async def get_manga_guild_ids(self, manga_id: str | int) -> list[int]:
        """
        Summary:
            Returns a list of guild ids that track the manga.

        Parameters:
            manga_id (str|int): The id of the manga.

        Returns:
            list[int]: list of guild ids that has subscribed to the manga.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT guild_id FROM tracked_guild_series WHERE series_id = $1;
                    """,
                    (manga_id,),
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return list(set([row[0] for row in result]))
                return []

    async def get_series_to_update(self) -> list[Manga] | None:
        """
        Summary:
            Returns a list of Manga class objects that needs to be updated.
            It needs to be updated when:
                - the manga is not completed

        Returns:
            list[Manga] | None: list of Manga class objects that needs to be updated.
        """
        async with aiosqlite.connect(self.db_name) as db:
            # only update series that are not completed and are subscribed to by at least one user
            async with db.execute(
                    """
                    SELECT * FROM series WHERE
                    completed = 0 AND id IN (
                        SELECT series_id FROM user_subs 
                        UNION SELECT series_id FROM bookmarks 
                        UNION SELECT series_id FROM tracked_guild_series
                        );
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return None

    async def get_user_bookmark(self, user_id: int, series_id: str) -> Bookmark | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    b.user_id,
                    b.series_id,
                    b.last_read_chapter_index,
                    b.guild_id,
                    b.last_updated_ts,
                    b.user_created,
                    
                    s.id,
                    s.human_name,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.completed,
                    s.scanlator
                    
                FROM bookmarks AS b
                INNER JOIN series AS s ON b.series_id = s.id
                WHERE user_id = $1 AND series_id = $2;
                """,
                (user_id, series_id),
            )
            result = await cursor.fetchone()
            if result is not None:
                result = list(result)
                bookmark_params, manga_params = result[:-9], tuple(result[-9:])

                manga = Manga.from_tuple(manga_params)
                # replace series_id with a manga object
                bookmark_params[1] = manga
                return Bookmark.from_tuple(tuple(bookmark_params))

    async def get_user_bookmarks(self, user_id: int) -> list[Bookmark] | None:
        """
        Summary:
            Returns a list of Bookmark class objects each representing a manga the user is subscribed to.

        Args:
            user_id: The user's id.

        Returns:
            List[Bookmark] if bookmarks are found.
            None if no bookmarks are found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    b.user_id,
                    b.series_id,
                    b.last_read_chapter_index,
                    b.guild_id,
                    b.last_updated_ts,
                    b.user_created,
                    
                    s.id,
                    s.human_name,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.completed,
                    s.scanlator
                    
                FROM bookmarks AS b
                INNER JOIN series AS s
                ON b.series_id = s.id
                WHERE b.user_id = $1 AND b.user_created = 1;
                """,
                (user_id,),
            )
            # INNER JOIN user_subs
            # ON b.user_id = u.id AND b.series_id = u.series_id
            result = await cursor.fetchall()
            if result:
                # change all the series_id to manga objects
                new_result: list = []
                for result_tup in list(result):
                    manga_params = result_tup[-9:]
                    manga = Manga.from_tuple(manga_params)
                    bookmark_params = result_tup[:-9]
                    bookmark_params = list(bookmark_params)
                    bookmark_params[1] = manga
                    new_result.append(tuple(bookmark_params))
                return Bookmark.from_tuples(new_result)

    async def get_user_bookmarks_autocomplete(self, user_id: int, current: str = None) -> list[tuple[int, str]]:
        async with aiosqlite.connect(self.db_name) as db:
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                cursor = await db.execute(
                    """
                    SELECT series.id, series.human_name FROM series 
                    JOIN bookmarks ON series.id = bookmarks.series_id 
                    WHERE bookmarks.user_id = $1 AND bookmarks.user_created = 1
                    ORDER BY levenshtein(human_name, $2) DESC
                    LIMIT 25;
                    """,
                    (user_id, current),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT series.id, series.human_name FROM series 
                    JOIN bookmarks ON series.id = bookmarks.series_id 
                    WHERE bookmarks.user_id = $1 AND bookmarks.user_created = 1;
                    """,
                    (user_id,),
                )
            result = await cursor.fetchall()
            if result:
                return [tuple(result) for result in result]

    async def get_series_chapters(
            self, series_id: str, current: str = None
    ) -> list[Chapter]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT available_chapters FROM series
                WHERE id = $1;
                """,
                (series_id,),
            )
            result = await cursor.fetchone()
            if result:
                result = result[0]
                chapters = Chapter.from_many_json(result)
                if current is not None and bool(current.strip()) is True:
                    return list(
                        sorted(
                            chapters, key=lambda x: _levenshtein_distance(x.name, current), reverse=True
                        )
                    )
                return chapters

    async def get_guild_config(self, guild_id: int) -> GuildSettings | None:
        """
        Returns:
             Optional[GuildSettings] object if a config is found for the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM guild_config WHERE guild_id = $1;
                    """,
                    (guild_id,),
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    return GuildSettings(self.client, *result)

    async def get_many_guild_config(self, guild_ids: list[int]) -> list[GuildSettings] | None:
        """
        Summary:
            Returns a list of GuildSettings objects for the specified guilds.

        Parameters:
            guild_ids (list[int]): A list of guild ids.

        Returns:
            List[GuildSettings] if guilds are found.
            None if no guilds are found.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM guild_config WHERE guild_id IN ({});
                    """.format(
                        ", ".join("?" * len(guild_ids))
                    ),
                    guild_ids,
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return [GuildSettings(self.client, *guild) for guild in result]

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
                    manga_obj = Manga.from_tuple(result)
                    if manga_obj.scanlator in SCANLATORS:
                        return (await SCANLATORS[manga_obj.scanlator].load_manga_objects([manga_obj]))[0]

    async def get_series_title(self, series_id: str) -> str | None:
        """
        Summary:
            Returns the 'human_name' of a series.

        Args:
            series_id: The id of the series.

        Returns:
            str | None: The title of the series.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT human_name FROM series WHERE id = ?;
                    """,
                    (series_id,),
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    return result[0]

    async def get_all_series(self, current: str = None, *, autocomplete: bool = False) -> list[Manga] | None:
        """
        Returns a list of Manga objects containing all series in the database.
        >>> [Manga, ...)]
        """
        if current is not None and bool(current.strip()) is True:
            async with aiosqlite.connect(self.db_name) as db:
                await db.create_function("levenshtein", 2, _levenshtein_distance)

                async with db.execute(
                        """
                        SELECT * FROM series
                        ORDER BY levenshtein(human_name, ?) DESC
                        LIMIT 25;
                        """, (current,)
                ) as cursor:
                    if result := await cursor.fetchall():
                        return Manga.from_tuples(result)
        elif autocomplete:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute(
                        """
                        SELECT * FROM series LIMIT 25;
                        """
                ) as cursor:
                    if result := await cursor.fetchall():
                        objects = Manga.from_tuples(result)
                        return [
                            (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                            for x in objects if x.scanlator in SCANLATORS
                        ]
        else:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute(
                        """
                        SELECT * FROM series;
                        """
                ) as cursor:
                    if result := await cursor.fetchall():
                        objects = Manga.from_tuples(result)
                        return [
                            (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                            for x in objects if x.scanlator in SCANLATORS
                        ]

    async def get_all_subscribed_series(self) -> list[Manga]:
        """
        Returns a list of tuples containing all series that are subscribed to by at least one user.
        >>> [Manga, ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM series WHERE series.id IN (
                        SELECT series_id FROM user_subs
                    );
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if not result:
                    return []
                else:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]

    async def update_series(self, manga: Manga) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            result = await db.execute(
                """
    UPDATE series SET last_chapter = $1, series_cover_url = $2, available_chapters = $3, completed = $4 WHERE id = $5;
                """,
                (
                    manga.last_chapter.to_json() if manga.last_chapter is not None else None,
                    manga.cover_url,
                    manga.chapters_to_text(),
                    manga.completed,
                    manga.id),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {manga.id} was found.")
            await db.commit()

    async def update_last_read_chapter_index(self, user_id: int, series_id: str, last_read_chapter_index: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
        UPDATE bookmarks SET last_read_chapter_index = $1, last_updated_ts = $2 WHERE user_id = $3 AND series_id = $4;
                """,
                (last_read_chapter_index, datetime.now().timestamp(), user_id, series_id),
            )
            await db.commit()

    async def delete_series(self, series_id: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM series WHERE id = $1;
                """,
                (series_id,),
            )

            await db.commit()

    async def delete_bookmark(self, user_id: int, series_id: str) -> bool:
        """
        Summary:
            Deletes a bookmark from the database.

        Parameters:
            user_id: The ID of the user whose bookmark is to be deleted.
            series_id: The ID of the series to be deleted.

        Returns:
            True if the bookmark was deleted successfully, False otherwise.
        """
        async with aiosqlite.connect(self.db_name) as db:
            success = await db.execute(
                """
                DELETE FROM bookmarks WHERE user_id = $1 and series_id = $2;
                """,
                (user_id, series_id),
            )
            await db.execute(
                """
                DELETE FROM series WHERE id = $1 AND id NOT IN (
                    SELECT series_id FROM user_subs
                );
                """,
                (series_id,),
            )
            await db.commit()
            return success.rowcount > 0

    async def unsub_user(self, user_id: int, series_id: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM user_subs WHERE id = $1 and series_id = $2;
                """,
                (user_id, series_id),
            )

            await db.commit()

    async def delete_config(self, guild_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM guild_config WHERE guild_id = $1;
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

    async def get_webhooks(self) -> set[str]:
        """
        Returns a set of all webhook URLs in the config table.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT notifications_webhook FROM guild_config;
                    """
            ) as cursor:
                return set([url for url, in await cursor.fetchall()])

    async def get_guild_manga_role_id(self, guild_id: int, manga_id: str) -> int | None:
        """
        Summary:
            Returns the role ID to ping for the manga set in the guild's config.

        Args:
            guild_id: The guild's ID
            manga_id: The manga's ID

        Returns:
            int | None: The role ID to ping for the manga set in the guild's config.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT role_id FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2;
                """,
                (guild_id, manga_id),
            )
            result = await cursor.fetchone()
            if result:
                return result[0]
            return None

    async def upsert_guild_sub_role(self, guild_id: int, manga_id: str, ping_role_id: int | discord.Role):
        """
        Summary:
            Sets the role ID to ping for the tracked manga

        Args:
            guild_id: int - The guild's ID
            manga_id: str - The manga's ID
            ping_role_id: int - The role's ID

        Returns:
            None
        """
        if isinstance(ping_role_id, discord.Role):
            ping_role_id = ping_role_id.id
        await self.execute(
            """
            INSERT INTO tracked_guild_series (guild_id, series_id, role_id) VALUES ($1, $2, $3)
            ON CONFLICT(guild_id, series_id) DO UPDATE SET role_id = $3;
            """,
            guild_id, manga_id, ping_role_id
        )

    async def delete_manga_track_instance(self, guild_id: int, manga_id: str):
        """
        Summary:
            Deletes the manga track instance from the database.

        Args:
            guild_id: int - The guild's ID
            manga_id: str - The manga's ID

        Returns:
            None
        """
        await self.execute(
            """
            DELETE FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2
            """,
            guild_id, manga_id
        )

    async def get_all_guild_tracked_manga(self, guild_id: int, current: str = None) -> list[Manga]:
        """
        Summary:
            Returns a list of Manga class objects that are tracked in the guild.

        Args:
            guild_id: int - The guild's ID
            current: str - The current search query

        Returns:
            list[Manga]: A list of Manga class objects that are tracked in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            await db.create_function("levenshtein", 2, _levenshtein_distance)
            if current is not None and bool(current.strip()) is True:
                query = """
                    SELECT * FROM series WHERE id IN (SELECT series_id FROM tracked_guild_series WHERE guild_id = $1)
                    ORDER BY levenshtein(human_name, $2)
                    DESC
                    LIMIT 25;
                """
                params = (guild_id, current)
            else:
                query = """
                    SELECT * FROM series WHERE id IN (SELECT series_id FROM tracked_guild_series WHERE guild_id = $1);
                """
                params = (guild_id,)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return []

    async def is_manga_tracked(self, guild_id: int, manga_id: str) -> bool:
        """
        Summary:
            Checks if a manga is tracked in the guild.

        Args:
            guild_id: int - The guild's ID
            manga_id: str - The manga's ID

        Returns:
            bool: Whether the manga is tracked in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT * FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2;
                """,
                (guild_id, manga_id),
            )
            result = await cursor.fetchone()
            return result is not None

    async def delete_guild_user_subs(self, guild_id: int) -> int:
        """
        Summary:
            Deletes all user subscriptions in the guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            int: The number of rows deleted.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                DELETE FROM user_subs WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            await db.commit()
            return cursor.rowcount

    async def delete_guild_tracked_series(self, guild_id: int) -> int:
        """
        Summary:
            Deletes all tracked series in the guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            int: The number of rows deleted.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                DELETE FROM tracked_guild_series WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            await db.commit()
            return cursor.rowcount

    async def get_user_untracked_subs(self, user_id: int, guild_id: int | None = None) -> list[Manga]:
        """
        Summary:
            Returns a list of Manga class objects
            that are subscribed to by the user but not tracked in the guild.

        Args:
            user_id: int - The user's ID
            guild_id: int | None - The guild's ID. If None, show all untracked manga subbed to by the user.

        Returns:
            list[Manga]:
            A list of Manga class objects that are subscribed to by the user but not tracked in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            SELECT * FROM series WHERE id IN (SELECT series_id FROM user_subs WHERE id = $1)
                    AND id NOT IN (SELECT series_id FROM tracked_guild_series
                    """
            if guild_id is not None:
                query += " WHERE guild_id = $2);"
                params = (user_id, guild_id)
            else:
                query += ");"
                params = (user_id,)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await SCANLATORS[x.scanlator].load_manga_objects([x]))[0]
                        for x in objects if x.scanlator in SCANLATORS
                    ]
                return []

    async def has_untracked_subbed_manga(self, user_id: int, guild_id: int | None = None) -> bool:
        """
        Summary:
            Checks if the user has subscribed to any manga that is not tracked in the guild.
        Args:
            user_id: int - The user's ID
            guild_id: int | None - The guild's ID. If None, show all untracked manga subbed to by the user.

        Returns:
            bool: Whether the user has subscribed to any manga that is not tracked in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            SELECT * FROM series 
                WHERE id IN (
                    SELECT series_id FROM user_subs WHERE id = $1
                    )
                AND id NOT IN (
                    SELECT series_id FROM tracked_guild_series
                """
            if guild_id is not None:
                query += " WHERE guild_id = $2) LIMIT 1;"
                params = (user_id, guild_id)
            else:
                query += ") LIMIT 1;"
                params = (user_id,)
            cursor = await db.execute(query, params)
            result = await cursor.fetchone()
            return result is not None

    async def unsubscribe_user_from_all_untracked(self, user_id: int, guild_id: int | None = None) -> int:
        """
        Summary:
            Unsubscribes the user from all manga that is not tracked in the guild.

        Args:
            user_id: int - The user's ID
            guild_id: int | None - The guild's ID. If None,
                unsubscribe from all untracked manga subbed to by the user.

        Returns:
            int: The number of rows deleted.
        """
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            DELETE FROM user_subs 
                WHERE id = $1 
                AND series_id NOT IN (
                    SELECT series_id 
                    FROM tracked_guild_series
            """
            if guild_id is not None:
                query += " WHERE tracked_guild_series.guild_id = $2);"
                params = (user_id, guild_id)
            else:
                query += ");"
                params = (user_id,)
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.rowcount

    async def get_guild_tracked_role_ids(self, guild_id: int) -> list[int] | None:
        """
        Summary:
            Returns a list of role IDs that are tracked in the guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            list[int] | None: A list of role IDs that are tracked in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT role_id FROM tracked_guild_series WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            result = await cursor.fetchall()
            if result:
                return [row[0] for row in result]
            return None

    async def update_guild_tracked_series_ping_role(self, guild_id: int, old_role_id: int | None, new_role_id: int):
        """
        Summary:
            Update the ping role for tracked manga with a default role id
        Args:
            guild_id: int - The guild's ID
            old_role_id: int - The role ID to be replaced
            new_role_id: int - The role ID to replace with

        Returns:
            None
        """
        if old_role_id is None:
            query = """
                UPDATE tracked_guild_series SET role_id = $1 WHERE guild_id = $2 AND role_id IS NULL;
            """
            params = (new_role_id, guild_id)
        else:
            query = """
                UPDATE tracked_guild_series SET role_id = $1 WHERE guild_id = $2 AND role_id = $3;
            """
            params = (new_role_id, guild_id, old_role_id)
        await self.execute(
            query,
            *params
        )

    async def add_bot_created_role(self, guild_id: int, role_id: int) -> None:
        """
        Summary:
            Adds a bot-created role to the database.
        Args:
            guild_id: int - The guild's ID
            role_id: int - The role's ID

        Returns:
            None
        """
        await self.execute(
            """
            INSERT INTO bot_created_roles (guild_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING;
            """,
            guild_id, role_id
        )

    async def remove_bot_created_role(self, guild_id: int, role_id: int) -> None:
        """
        Summary:
            Removes a bot-created role from the database.
        Args:
            guild_id: int - The guild's ID
            role_id: int - The role's ID

        Returns:
            None
        """
        await self.execute(
            """
            DELETE FROM bot_created_roles WHERE guild_id = $1 AND role_id = $2;
            """,
            guild_id, role_id
        )

    async def get_all_guild_bot_created_roles(self, guild_id: int) -> list[int]:
        """
        Summary:
            Returns a list of bot-created role IDs in the guild.
        Args:
            guild_id: int - The guild's ID

        Returns:
            list[int]: A list of bot-created role IDs in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT role_id FROM bot_created_roles WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            result = await cursor.fetchall()
            if result:
                return [row[0] for row in result]
            return []

    async def delete_all_guild_created_roles(self, guild_id: int) -> None:
        """
        Summary:
            Deletes all bot-created roles in the guild.
        Args:
            guild_id: int - The guild's ID

        Returns:
            None
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    DELETE FROM bot_created_roles WHERE guild_id = $1;
                    """,
                    (guild_id,)
            ) as cursor:
                await db.commit()
                return cursor.rowcount
