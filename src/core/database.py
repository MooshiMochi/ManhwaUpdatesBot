from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable, List, Optional, TYPE_CHECKING

import aiosqlite
import discord
from fuzzywuzzy import fuzz

from ..static import Constants

if TYPE_CHECKING:
    from .bot import MangaClient

from src.core.objects import GuildSettings, Manga, Bookmark, Chapter, MangaHeader, Patron, ScanlatorChannelAssociation, \
    SubscriptionObject
from src.core.scanlators import scanlators
from io import BytesIO
import pandas as pd
import sqlite3
from src.core.errors import CustomError, DatabaseError

completed_db_set = ",".join(map(lambda x: f"'{x.lower()}'", Constants.completed_status_set))


def _levenshtein_distance(a: str, b: str) -> int:
    return fuzz.ratio(a, b)


class Database:
    def __init__(self, bot: MangaClient, database_name: str = "database.db"):
        self.bot: MangaClient = bot
        self.db_name = database_name

        if not os.path.exists(self.db_name):
            with open(self.db_name, "w") as _:
                ...

    async def async_init(self) -> None:
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS series (
                    id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    synopsis TEXT,
                    series_cover_url TEXT NOT NULL,
                    last_chapter TEXT,
                    available_chapters TEXT,
                    
                    status TEXT NOT NULL DEFAULT 'Ongoing',
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    UNIQUE(id, scanlator) ON CONFLICT IGNORE
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_subs (
                    id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    UNIQUE (id, series_id, scanlator, guild_id) ON CONFLICT IGNORE
                )
                """
=======
        self.conn = await aiosqlite.connect(self.db_name)
        # Register the levenshtein function once during initialization
        await self.conn.create_function("levenshtein", 2, _levenshtein_distance)

        # Enable WAL mode for better concurrency and performance
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        # Set a larger cache size for better performance
        await self.conn.execute("PRAGMA cache_size=-10000;")  # ~10MB cache
        # Enable foreign key constraints
        await self.conn.execute("PRAGMA foreign_keys=ON;")

        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
                id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                synopsis TEXT,
                series_cover_url TEXT NOT NULL,
                last_chapter TEXT,
                available_chapters TEXT,

                status TEXT NOT NULL DEFAULT 'Ongoing',
                scanlator TEXT NOT NULL DEFAULT 'Unknown',
                UNIQUE(id, scanlator) ON CONFLICT IGNORE
            )
            """
        )
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_subs (
                id INTEGER NOT NULL,
                series_id TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                scanlator TEXT NOT NULL DEFAULT 'Unknown',

                FOREIGN KEY (series_id) REFERENCES series (id),
                FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                UNIQUE (id, series_id, scanlator, guild_id) ON CONFLICT IGNORE
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
            )

<<<<<<< HEAD
            await db.execute(
                # user_id: the discord ID of the user the bookmark belongs to
                # series_id: the ID of the series from the series table
                # last_read_chapter_index: the last chapter the user read
                # guild_id: the discord guild the user bookmarked the manga from
                # last_updated_ts: the timestamp of the last time the bookmark was updated by the user
                # fold: the folder in which the bookmark is in
                """
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    last_read_chapter_index INTEGER DEFAULT NULL,
                    guild_id INTEGER NOT NULL,
                    last_updated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    folder VARCHAR(10) DEFAULT 'reading',
                    
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                    FOREIGN KEY (user_id) REFERENCES user_subs (id),
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    UNIQUE (user_id, series_id, scanlator) ON CONFLICT IGNORE
                    );
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY NOT NULL,             
                    notifications_channel_id INTEGER,
                    default_ping_role_id INTEGER DEFAULT NULL,
                    auto_create_role BOOLEAN NOT NULL DEFAULT false,
                    system_channel_id INTEGER default null,
                    show_update_buttons BOOLEAN NOT NULL DEFAULT true,
                    paid_chapter_notifications BOOLEAN NOT NULL DEFAULT false,
                    bot_manager_role_id INTEGER DEFAULT NULL,
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
                    scanlator TEXT NOT NULL DEFAULT 'Unknown',
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                    UNIQUE (guild_id, series_id, scanlator) ON CONFLICT REPLACE
=======
        await self.conn.execute(
            # user_id: the discord ID of the user the bookmark belongs to
            # series_id: the ID of the series from the series table
            # last_read_chapter_index: the last chapter the user read
            # guild_id: the discord guild the user bookmarked the manga from
            # last_updated_ts: the timestamp of the last time the bookmark was updated by the user
            # fold: the folder in which the bookmark is in
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
                user_id INTEGER NOT NULL,
                series_id TEXT NOT NULL,
                last_read_chapter_index INTEGER DEFAULT NULL,
                guild_id INTEGER NOT NULL,
                last_updated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scanlator TEXT NOT NULL DEFAULT 'Unknown',
                folder VARCHAR(10) DEFAULT 'reading',

                FOREIGN KEY (series_id) REFERENCES series (id),
                FOREIGN KEY (scanlator) REFERENCES series (scanlator),
                FOREIGN KEY (user_id) REFERENCES user_subs (id),
                FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                UNIQUE (user_id, series_id, scanlator) ON CONFLICT IGNORE
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
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
            )

<<<<<<< HEAD
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS patreons (
                    email TEXT PRIMARY KEY NOT NULL,
                    user_id INTEGER,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    UNIQUE (email) ON CONFLICT REPLACE
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scanlator_channel_associations (
                    guild_id INTEGER NOT NULL,
                    scanlator TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    FOREIGN KEY (guild_id) REFERENCES guild_config (guild_id),
                    UNIQUE (guild_id, scanlator, channel_id) ON CONFLICT REPLACE
                );
                """
            )

            await db.commit()
=======
        # Create indexes for frequently queried columns to improve performance
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_series_id_scanlator ON series(id, scanlator);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_user_subs_user_id ON user_subs(id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_user_subs_series_id_scanlator ON user_subs(series_id, scanlator);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks(user_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_series_id_scanlator ON bookmarks(series_id, scanlator);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_guild_series_guild_id ON tracked_guild_series(guild_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_guild_series_series_id_scanlator ON tracked_guild_series(series_id, scanlator);")

        await self.conn.commit()
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

    async def execute(self, query: str, *args) -> Any:
        """
        Execute an SQL query and return the result.

        Args:
            query: The SQL query to execute.
            *args: The arguments to pass to the query.

        Returns:
            The result of the query.
        """
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            if levenshtein is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
            async with db.execute(query, args) as cursor:
                result = await cursor.fetchall()
                await db.commit()
                return result
=======
        async with self.conn.execute(query, args) as cursor:
            result = await cursor.fetchall()
            await self.conn.commit()
            return result
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

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

    async def untrack_completed_series(self, series_id: str, scanlator: str) -> int:
        """
        Remove a series from the tracked series table only if it is completed.

        Args:
            series_id: The ID of the series to untrack.
            scanlator: The scanlator of the series.

        Returns:
            The number of rows affected.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                f"""
                    DELETE FROM tracked_guild_series WHERE series_id = $1 AND scanlator = $2
                    AND (SELECT status FROM series WHERE id = $1 AND scanlator = $2) IN ({completed_db_set});
                    """,
                (series_id, scanlator)
            )
            await db.commit()
            return cursor.rowcount if cursor.rowcount > 0 else 0

    async def upsert_patreons(self, patrons: list[Patron]) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            for patron in patrons:
                await db.execute(
                    """
                    INSERT INTO patreons (email, user_id, first_name, last_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(email) DO UPDATE SET user_id = $2, first_name = $3, last_name = $4;
                    """,
                    patron.to_tuple(),
                )
            await db.commit()

    async def delete_inactive_patreons(self, active_patrons: list[Patron]) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM patreons WHERE email NOT IN ($1);
                """,
                (",".join([patron.email for patron in active_patrons]),),
            )
            await db.commit()

    async def is_patreon(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT * FROM patreons WHERE user_id = $1;
                """,
                (user_id,),
            )
            result = await cursor.fetchone()
            return result is not None

    async def subscribe_user_to_tracked_series(self, sub_objects: list[SubscriptionObject]) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.executemany(
                """
                INSERT INTO user_subs VALUES ($1, $2, $3, $4);
                """,
                map(lambda x: x.to_tuple(), sub_objects)
            )
            await db.commit()

    async def unsubscribe_user_to_tracked_series(self, sub_objects: list[SubscriptionObject]) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.executemany(
                """
                DELETE FROM user_subs WHERE id = $1 AND series_id = $2 AND guild_id = $3 AND scanlator = $4;
                """,
                map(lambda x: x.to_tuple(), sub_objects)
            )
            await db.commit()

    async def get_all_user_unsubbed_tracked_series(
            self, guild_id: int, user_id: int, guild: discord.Guild) -> list[SubscriptionObject] | list[Any]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    s.id,
                    s.scanlator,
                    t.role_id
                FROM series AS s
                INNER JOIN tracked_guild_series AS t
                ON s.id = t.series_id AND s.scanlator = t.scanlator
                WHERE t.guild_id = $1
                AND (s.id, s.scanlator) NOT IN (
                    SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1 AND id = $2
                );
                """,
                (guild_id, user_id),
            )
            result = await cursor.fetchall()
            if result:
                return [SubscriptionObject(user_id, guild_id, x[0], x[1], guild.get_role(x[2])) for x in result]
            return []

    async def get_all_user_subbed_series(
            self, guild_id: int, user_id: int, guild: discord.Guild) -> list[SubscriptionObject] | list[Any]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    s.id,
                    s.scanlator,
                    t.role_id
                FROM series AS s
                INNER JOIN user_subs AS u
                ON s.id = u.series_id AND s.scanlator = u.scanlator
                LEFT JOIN tracked_guild_series AS t
                ON s.id = t.series_id AND s.scanlator = t.scanlator AND t.guild_id = u.guild_id
                WHERE u.guild_id = $1 AND u.id = $2;
                """,
                (guild_id, user_id),
            )
            result = await cursor.fetchall()
            if result:
                return [SubscriptionObject(user_id, guild_id, x[0], x[1], guild.get_role(x[2])) for x in result]
            return []

    async def delete_role_from_db(self, role_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.executemany(
                """
                UPDATE tracked_guild_series SET role_id = NULL WHERE role_id = $1;
                DELETE FROM bot_created_roles WHERE role_id = $1;
                """,
                role_id
            )

    async def subscribe_user_to_all_tracked_series(self, user_id: int, guild_id: int) -> int:
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.status,
                    s.scanlator
                    
                FROM series AS s
                INNER JOIN tracked_guild_series AS t
                ON s.id = t.series_id AND s.scanlator = t.scanlator
                WHERE t.guild_id = $1
                AND (s.id, s.scanlator) NOT IN (
                    SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1
                );
                """,
                (guild_id,),
            )
            result = await cursor.fetchall()
            if result:
                mangas = Manga.from_tuples(result)
                for manga in mangas:
                    await self.subscribe_user(user_id, guild_id, manga.id, manga.scanlator)
                return len(mangas)
            return 0
=======
        cursor = await self.conn.execute(
            """
            SELECT
                s.id,
                s.title,
                s.url,
                s.synopsis,
                s.series_cover_url,
                s.last_chapter,
                s.available_chapters,
                s.status,
                s.scanlator

            FROM series AS s
            INNER JOIN tracked_guild_series AS t
            ON s.id = t.series_id AND s.scanlator = t.scanlator
            WHERE t.guild_id = $1
            AND (s.id, s.scanlator) NOT IN (
                SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1
            );
            """,
            (guild_id,),
        )
        result = await cursor.fetchall()
        if result:
            mangas = Manga.from_tuples(result)
            for manga in mangas:
                await self.subscribe_user(user_id, guild_id, manga.id, manga.scanlator)
            return len(mangas)
        return 0
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

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
            if manga_obj.scanlator in scanlators:
                await db.execute(
                    """
                INSERT INTO series (id, title, url, synopsis, series_cover_url, last_chapter, available_chapters, 
                status, scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id, scanlator) DO NOTHING;
                    """,
                    ((await scanlators[manga_obj.scanlator].unload_manga([manga_obj]))[0].to_tuple()),
                )

                await db.commit()
            else:
                raise CustomError(
                    f"This action cannot be completed at this time because {manga_obj.scanlator.title()} is currently "
                    f"disabled."
                )

    async def upsert_bookmark(self, bookmark: Bookmark) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            if bookmark.manga.scanlator in scanlators:
                await db.execute(
                    """
                INSERT INTO series (id, title, url, synopsis, series_cover_url, last_chapter, available_chapters, 
                status, scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id, scanlator) DO NOTHING;
                    """,
                    ((await scanlators[bookmark.manga.scanlator].unload_manga([bookmark.manga]))[0].to_tuple()),
                )
            else:
                raise CustomError(
                    f"This action cannot be completed at this time because {bookmark.manga.scanlator.title()} is "
                    f"currently disabled."
                )

            await db.execute(
                """
                INSERT INTO bookmarks (
                    user_id,
                    series_id,
                    last_read_chapter_index,
                    guild_id,
                    last_updated_ts,
                    scanlator,
                    folder
                    ) 
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT(user_id, series_id, scanlator) DO 
                UPDATE SET last_read_chapter_index=$3, last_updated_ts=$5, folder=$7;
                """,
                (bookmark.to_tuple()),
            )
            await db.commit()
            return True

    async def subscribe_user(self, user_id: int, guild_id: int, series_id: str, scanlator: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            # INSERT OR IGNORE INTO user_subs (id, series_id, guild_id) VALUES ($1, $2, $3);
            await db.execute(
                """
                INSERT INTO user_subs (id, series_id, guild_id, scanlator) 
                VALUES ($1, $2, $3, $4) 
                ON CONFLICT (id, series_id, guild_id, scanlator) DO NOTHING;
                """,
                (user_id, series_id, guild_id, scanlator),
            )

            await db.commit()

    async def is_user_subscribed(self, user_id: int, manga_id: Any, scanlator: str) -> bool:
        """
        Summary: Checks if a user is subscribed to a manga.

        Args:
            user_id: The user's ID.
            manga_id: The manga's ID.
            scanlator: The manga's scanlator.

        Returns:
            (bool): Whether the user is subscribed to the manga.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT * FROM user_subs WHERE id = $1 AND series_id = $2 AND scanlator = $3;
                """,
                (user_id, manga_id, scanlator),
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
                    user_id, series_id, last_read_chapter_index, guild_id, last_updated_ts, scanlator, folder
                    ) 
                VALUES ($1, $2, $3, $4, $5, $6, $7) 
                ON CONFLICT(user_id, series_id, scanlator) 
                DO UPDATE SET last_read_chapter_index = $3, last_updated_ts = $5;
                """,
                (user_id, manga.id, chapter.to_json(), guild_id, datetime.now(), manga.scanlator),
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
                    auto_create_role, system_channel_id, show_update_buttons, 
                    paid_chapter_notifications, bot_manager_role_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT(guild_id)
                DO UPDATE SET 
                    notifications_channel_id = $2, default_ping_role_id = $3, 
                    auto_create_role = $4, system_channel_id = $5, show_update_buttons = $6, 
                    paid_chapter_notifications = $7, bot_manager_role_id = $8
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
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            query = """
                SELECT
                    s.id,
                    s.title,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.status,
                    s.scanlator
                    
                FROM series AS s
                INNER JOIN user_subs AS u
                ON s.id = u.series_id AND s.scanlator = u.scanlator
                WHERE u.id = $1
                """
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                query += " ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
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
=======
        query = """
            SELECT
                s.id,
                s.title,
                s.url,
                s.synopsis,
                s.series_cover_url,
                s.last_chapter,
                s.available_chapters,
                s.status,
                s.scanlator

            FROM series AS s
            INNER JOIN user_subs AS u
            ON s.id = u.series_id AND s.scanlator = u.scanlator
            WHERE u.id = $1
            """
        if current is not None and bool(current.strip()) is True:
            query += " ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
            params = (user_id, current)
        else:
            query += ";"
            params = (user_id,)
        cursor = await self.conn.execute(
            query,
            params,
        )
        result = await cursor.fetchall()
        if result:
            return Manga.from_tuples(result)  # noqa
        return []
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

    # noinspection PyUnresolvedReferences
    async def get_user_guild_subs(
            self,
            guild_id: int,
            user_id: int,
            current: str = None,
            autocomplete: bool = False,
            scanlator: str | None = None
    ) -> list[Manga]:
        """
        Returns a list of Manga class objects each representing a manga the user is subscribed to.
        >>> [Manga, ...]
        >>> None if no manga is found.
        """
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            _base = (
                "SELECT * FROM series "
                "WHERE (series.id, series.scanlator) IN "
                "(SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1 AND "
                "id = $2)"
            )
            if autocomplete is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                is_current: bool = (current or "").strip() != ""
                if scanlator is not None and is_current is True:
                    query = f"{_base} AND scanlator = $3 ORDER BY levenshtein(title, $4) DESC LIMIT 25;"
                    params = (guild_id, user_id, scanlator, current)
                elif scanlator is not None and is_current is False:
                    query = f"{_base} AND scanlator = $3 LIMIT 25;"
                    params = (guild_id, user_id, scanlator)
                elif is_current is True:
                    query = f"{_base} ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                    params = (guild_id, user_id, current)
                else:  # current False, scanlator None
                    query = f"{_base} LIMIT 25;"
                    params = (guild_id, user_id)
            else:
                query = f"{_base};"
=======
        _base = (
            "SELECT * FROM series "
            "WHERE (series.id, series.scanlator) IN "
            "(SELECT series_id, scanlator FROM user_subs WHERE guild_id = $1 AND "
            "id = $2)"
        )
        if autocomplete is True:
            is_current: bool = (current or "").strip() != ""
            if scanlator is not None and is_current is True:
                query = f"{_base} AND scanlator = $3 ORDER BY levenshtein(title, $4) DESC LIMIT 25;"
                params = (guild_id, user_id, scanlator, current)
            elif scanlator is not None and is_current is False:
                query = f"{_base} AND scanlator = $3 LIMIT 25;"
                params = (guild_id, user_id, scanlator)
            elif is_current is True:
                query = f"{_base} ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                params = (guild_id, user_id, current)
            else:  # current False, scanlator None
                query = f"{_base} LIMIT 25;"
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
                params = (guild_id, user_id)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
                    ]
                return []

    async def get_user_subs(self, user_id: int, current: str = None) -> list[Manga]:
        """
        Returns a list of Manga class objects each representing a manga the user is subscribed to.
        >>> [Manga, ...]
        >>> None # if no manga is found.
        """
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            query = """
            SELECT * FROM series 
            WHERE (series.id, series.scanlator) IN (
                SELECT series_id, scanlator FROM user_subs WHERE id = $1
                )
            """
            if current is not None and bool(current.strip()) is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                query += " ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                params = (user_id, current)
            else:
                query += ";"
                params = (user_id,)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
                    ]
                return []
=======
        query = """
        SELECT * FROM series 
        WHERE (series.id, series.scanlator) IN (
            SELECT series_id, scanlator FROM user_subs WHERE id = $1
            )
        """
        if current is not None and bool(current.strip()) is True:
            query += " ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
            params = (user_id, current)
        else:
            query += ";"
            params = (user_id,)
        async with self.conn.execute(query, params) as cursor:
            result = await cursor.fetchall()
            if result:
                objects = Manga.from_tuples(result)
                return [
                    (await scanlators[x.scanlator].load_manga([x]))[0]
                    for x in objects if x.scanlator in scanlators
                ]
            return []
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

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
                    SELECT * FROM series
                    WHERE (series.id, series.scanlator) NOT IN (
                        SELECT series_id, scanlator FROM user_subs
                    )
                    AND (series.id, series.scanlator) NOT IN (
                        SELECT series_id, scanlator FROM bookmarks
                    );
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
                    ]
                return None

    async def get_manga_guild_ids(self, manga_id: str | int, scanlator: str) -> list[int]:
        """
        Summary:
            Returns a list of guild ids that track the manga.

        Parameters:
            manga_id (str|int): The id of the manga.
            scanlator (str): The scanlator of the manga.

        Returns:
            list[int]: list of guild ids that has subscribed to the manga.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT guild_id FROM tracked_guild_series WHERE series_id = $1 and scanlator = $2;
                    """,
                    (manga_id, scanlator),
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return list(set([row[0] for row in result]))
                return []

    async def get_series_to_update(self) -> list[MangaHeader] | None:
        """
        Summary:
            Returns a list of Manga class objects that needs to be updated.
            It needs to be updated when:
                - the manga is not completed

        Returns:
            list[MangHeader] | None: list of Manga class objects that needs to be updated.
        """
        async with aiosqlite.connect(self.db_name) as db:
            # only update series that are not completed and are subscribed to by at least one user
            async with db.execute(
                    f"""
                    SELECT id, scanlator FROM series WHERE
                        (id, scanlator) IN (
                            SELECT series_id, scanlator FROM user_subs
                            UNION
                            SELECT series_id, scanlator FROM bookmarks
                            UNION
                            SELECT series_id, scanlator FROM tracked_guild_series
                        )
                        AND scanlator NOT IN (SELECT scanlator FROM scanlators_config WHERE enabled = false)
                        AND lower(status) NOT IN ({completed_db_set});
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return [MangaHeader(*row) for row in result]
                return None

    async def get_user_bookmark(self, user_id: int, series_id: str, scanlator: str) -> Bookmark | None:
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    b.user_id,
                    b.series_id,
                    b.last_read_chapter_index,
                    b.guild_id,
                    b.last_updated_ts,
                    b.folder,
                    
                    s.id,
                    s.title,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.status,
                    s.scanlator
                                
                FROM bookmarks AS b
                INNER JOIN series AS s ON (b.series_id = s.id AND b.scanlator = s.scanlator)
                WHERE b.user_id = $1 AND b.series_id = $2 AND b.scanlator = $3;
                """,
                (user_id, series_id, scanlator),
            )
            result = await cursor.fetchone()
            if result is not None:
                result = list(result)
                bookmark_params, manga_params = result[:-9], tuple(result[-9:])
=======
        cursor = await self.conn.execute(
            """
            SELECT
                b.user_id,
                b.series_id,
                b.last_read_chapter_index,
                b.guild_id,
                b.last_updated_ts,
                b.folder,

                s.id,
                s.title,
                s.url,
                s.synopsis,
                s.series_cover_url,
                s.last_chapter,
                s.available_chapters,
                s.status,
                s.scanlator

            FROM bookmarks AS b
            INNER JOIN series AS s ON (b.series_id = s.id AND b.scanlator = s.scanlator)
            WHERE b.user_id = $1 AND b.series_id = $2 AND b.scanlator = $3;
            """,
            (user_id, series_id, scanlator),
        )
        result = await cursor.fetchone()
        if result is not None:
            result = list(result)
            bookmark_params, manga_params = result[:-9], tuple(result[-9:])
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

                manga = Manga.from_tuple(manga_params)
                if manga.scanlator not in scanlators:
                    raise CustomError(
                        f"This action cannot be completed at this time because {manga.scanlator.title()} is currently "
                        f"disabled."
                    )
                manga = (await scanlators[manga.scanlator].load_manga([manga]))[0]
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
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    b.user_id,
                    b.series_id,
                    b.last_read_chapter_index,
                    b.guild_id,
                    b.last_updated_ts,
                    b.folder,
                    
                    s.id,
                    s.title,
                    s.url,
                    s.synopsis,
                    s.series_cover_url,
                    s.last_chapter,
                    s.available_chapters,
                    s.status,
                    s.scanlator
                                
                FROM bookmarks AS b
                INNER JOIN series AS s ON (b.series_id = s.id AND b.scanlator = s.scanlator)
                WHERE b.user_id = $1;
                """,
                (user_id,),
            )
=======
        cursor = await self.conn.execute(
            """
            SELECT
                b.user_id,
                b.series_id,
                b.last_read_chapter_index,
                b.guild_id,
                b.last_updated_ts,
                b.folder,

                s.id,
                s.title,
                s.url,
                s.synopsis,
                s.series_cover_url,
                s.last_chapter,
                s.available_chapters,
                s.status,
                s.scanlator

            FROM bookmarks AS b
            INNER JOIN series AS s ON (b.series_id = s.id AND b.scanlator = s.scanlator)
            WHERE b.user_id = $1;
            """,
            (user_id,),
        )
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)

            result = await cursor.fetchall()
            if result:
                # change all the series_id to manga objects
                new_result: list = []
                for result_tup in list(result):
                    manga_params = result_tup[-9:]
                    manga = Manga.from_tuple(manga_params)
                    if manga.scanlator not in scanlators:
                        continue
                    manga = (await scanlators[manga.scanlator].load_manga([manga]))[0]

                    bookmark_params = result_tup[:-9]
                    bookmark_params = list(bookmark_params)
                    bookmark_params[1] = manga
                    new_result.append(tuple(bookmark_params))
                return Bookmark.from_tuples(new_result)

    async def get_user_bookmarks_autocomplete(
            self, user_id: int, current: str = None, autocomplete: bool = False, scanlator: str | None = None
    ) -> list[tuple[int, str]]:
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            _base = (
                "SELECT series.id, series.title, series.scanlator FROM series "
                "JOIN bookmarks ON series.id = bookmarks.series_id AND series.scanlator = bookmarks.scanlator "
                "WHERE bookmarks.user_id = $1 AND bookmarks.folder != 'hidden'"
            )
            if autocomplete is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                is_current: bool = (current or "").strip() != ""
                if scanlator is not None and is_current is True:
                    query = f"{_base} AND series.scanlator = $2 ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                    params = (user_id, scanlator, current)
                elif scanlator is not None and is_current is False:
                    query = f"{_base} AND series.scanlator = $2 LIMIT 25;"
                    params = (user_id, scanlator)
                elif is_current is True:
                    query = f"{_base} ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                    params = (user_id, current)
                else:
                    query = f"{_base} LIMIT 25;"
                    params = (user_id,)
                cursor = await db.execute(query, params)
=======
        _base = (
            "SELECT series.id, series.title, series.scanlator FROM series "
            "JOIN bookmarks ON series.id = bookmarks.series_id AND series.scanlator = bookmarks.scanlator "
            "WHERE bookmarks.user_id = $1 AND bookmarks.folder != 'hidden'"
        )
        if autocomplete is True:
            is_current: bool = (current or "").strip() != ""
            if scanlator is not None and is_current is True:
                query = f"{_base} AND series.scanlator = $2 ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                params = (user_id, scanlator, current)
            elif scanlator is not None and is_current is False:
                query = f"{_base} AND series.scanlator = $2 LIMIT 25;"
                params = (user_id, scanlator)
            elif is_current is True:
                query = f"{_base} ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                params = (user_id, current)
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
            else:
                cursor = await db.execute(f"{_base};", (user_id,))
            result = await cursor.fetchall()
            if result:
                return [tuple(result) for result in result]

    async def get_series_chapters(
            self, series_id: str, scanlator: str, current: str = None
    ) -> list[Chapter]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT available_chapters FROM series
                WHERE id = $1 and scanlator = $2;
                """,
                (series_id, scanlator),
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
                    return GuildSettings(self.bot, *result)

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
                    return [GuildSettings(self.bot, *guild) for guild in result]

    async def get_series(self, series_id: str, scanlator: str) -> Manga | None:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM series WHERE id = $1 AND scanlator = $2;
                    """,
                    (series_id, scanlator),
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    manga_obj = Manga.from_tuple(result)
                    if manga_obj.scanlator in scanlators:
                        return (await scanlators[manga_obj.scanlator].load_manga([manga_obj]))[0]

    async def get_series_title(self, series_id: str, scanlator: str) -> str | None:
        """
        Summary:
            Returns the 'title' of a series.

        Args:
            series_id: The id of the series.
            scanlator: The scanlator of the series.

        Returns:
            str | None: The title of the series.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT title FROM series WHERE id = $1 and scanlator = $2;
                    """,
                    (series_id, scanlator)
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    return result[0]

    async def get_all_series(
            self, current: str = None, *, autocomplete: bool = False, scanlator: str = None
    ) -> list[Manga] | None:
        """
        Returns a list of Manga objects containing all series in the database.
        >>> [Manga, ...)]
        """
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            if autocomplete is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                is_current: bool = (current or "").strip() != ""
                if scanlator is not None and is_current is True:
                    query = "SELECT * FROM series WHERE scanlator = $1 ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                    params = (scanlator, current)
                elif scanlator is not None and is_current is False:
                    query = "SELECT * FROM series WHERE scanlator = $1 LIMIT 25;"
                    params = (scanlator,)
                elif is_current is True:
                    query = "SELECT * FROM series ORDER BY levenshtein(title, $1) DESC LIMIT 25;"
                    params = (current,)
                else:
                    query = "SELECT * FROM series LIMIT 25;"
                    params = None
                async with db.execute(query, params) as cursor:
                    if result := await cursor.fetchall():
                        return [x for x in Manga.from_tuples(result) if not x.completed]
=======
        if autocomplete is True:
            is_current: bool = (current or "").strip() != ""
            if scanlator is not None and is_current is True:
                query = "SELECT * FROM series WHERE scanlator = $1 ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                params = (scanlator, current)
            elif scanlator is not None and is_current is False:
                query = "SELECT * FROM series WHERE scanlator = $1 LIMIT 25;"
                params = (scanlator,)
            elif is_current is True:
                query = "SELECT * FROM series ORDER BY levenshtein(title, $1) DESC LIMIT 25;"
                params = (current,)
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
            else:
                async with db.execute("SELECT * FROM series;") as cursor:
                    if result := await cursor.fetchall():
                        objects = Manga.from_tuples(result)
                        return [
                            (await scanlators[x.scanlator].load_manga([x]))[0]
                            for x in objects if x.scanlator in scanlators
                        ]

    async def get_all_subscribed_series(self) -> list[Manga]:
        """
        Returns a list of tuples containing all series that are subscribed to by at least one user.
        >>> [Manga, ...)]
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT * FROM series WHERE (series.id, series.scanlator) IN (
                        SELECT series_id, scanlator FROM user_subs
                    );
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if not result:
                    return []
                else:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
                    ]

    async def update_series(self, manga: Manga) -> None:
        # since the update_series is only called in the update check, we don't need to worry about whether the
        # scanlator is disabled, as they are removed form the check loop if they are disabled
        if manga.scanlator not in scanlators:
            raise CustomError(
                f"This action cannot be completed at this time because {manga.scanlator.title()} is currently disabled."
            )
        manga = (await scanlators[manga.scanlator].unload_manga([manga]))[0]
        async with aiosqlite.connect(self.db_name) as db:
            result = await db.execute(
                """
                    UPDATE series 
                    SET last_chapter = $1, series_cover_url = $2, available_chapters = $3, status = $4 
                    WHERE id = $5 AND scanlator = $6;
                """,
                (
                    manga.last_chapter.to_json() if manga.last_chapter is not None else None,
                    manga.cover_url,
                    manga.chapters_to_text(),
                    manga.status,
                    manga.id,
                    manga.scanlator
                ),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {manga.id} was found.")
            await db.commit()

    async def update_last_read_chapter_index(
            self, user_id: int, series_id: str, scanlator: str, last_read_chapter_index: int
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                    UPDATE bookmarks 
                    SET last_read_chapter_index = $1, last_updated_ts = $2 
                    WHERE user_id = $3 AND series_id = $4 AND scanlator = $5;
                """,
                (last_read_chapter_index, datetime.now().timestamp(), user_id, series_id, scanlator),
            )
            await db.commit()

    async def update_bookmark_folder(self, bookmark: Bookmark) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                UPDATE bookmarks
                SET folder = $1
                WHERE user_id = $2 AND series_id = $3 AND scanlator = $4;
                """,
                (bookmark.folder.value, bookmark.user_id, bookmark.manga.id, bookmark.manga.scanlator)
            )
            await db.commit()

    async def delete_series(self, series_id: str, scanlator: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM series WHERE id = $1 AND scanlator = $2;
                """,
                (series_id, scanlator),
            )

            await db.commit()

    async def delete_bookmark(self, user_id: int, series_id: str, scanlator: str) -> bool:
        """
        Summary:
            Deletes a bookmark from the database.

        Parameters:
            user_id: The ID of the user whose bookmark is to be deleted.
            series_id: The ID of the series to be deleted.
            scanlator: The scanlator of the bookmarked manga to delete

        Returns:
            True if the bookmark was deleted successfully, False otherwise.
        """
        async with aiosqlite.connect(self.db_name) as db:
            success = await db.execute(
                """
                DELETE FROM bookmarks WHERE user_id = $1 and series_id = $2 and scanlator = $3;
                """,
                (user_id, series_id, scanlator),
            )
            await db.execute(
                """
                DELETE FROM series WHERE id = $1 AND scanlator = $2 AND (id, scanlator) NOT IN (
                    SELECT series_id, scanlator FROM user_subs
                );
                """,
                (series_id, scanlator),
            )
            await db.commit()
            return success.rowcount > 0

    async def unsub_user(self, user_id: int, series_id: str, scanlator: str) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM user_subs WHERE id = $1 and series_id = $2 and scanlator = $3;
                """,
                (user_id, series_id, scanlator),
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
            self, series_ids_and_scanlators: Iterable[tuple[str, str]]
    ) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.cursor() as cursor:
                for _id, scanlator_str in series_ids_and_scanlators:
                    await cursor.execute(
                        """
                        DELETE FROM series WHERE id = $1 AND scanlator = $2;
                        """, (_id, scanlator_str)
                    )
                await db.commit()

    async def get_guild_manga_role_id(self, guild_id: int, manga_id: str, scanlator: str) -> int | None:
        """
        Summary:
            Returns the role ID to ping for the manga set in the guild's config.

        Args:
            guild_id: The guild's ID
            manga_id: The manga's ID
            scanlator: The manga's scanlator

        Returns:
            int | None: The role ID to ping for the manga set in the guild's config.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT role_id FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2 and scanlator = $3 AND
                role_id IS NOT (SELECT default_ping_role_id FROM guild_config WHERE guild_id = $1);
                """,
                (guild_id, manga_id, scanlator),
            )
            result = await cursor.fetchone()
            if result:
                return result[0]
            return None

    async def upsert_guild_sub_role(
            self, guild_id: int, manga_id: str, scanlator: str, ping_role_id: int | discord.Role
    ) -> None:
        """
        Summary:
            Sets the role ID to ping for the tracked manga

        Args:
            guild_id: int - The guild's ID
            manga_id: str - The manga's ID
            scanlator: str - The manga's scanlator
            ping_role_id: int - The role's ID

        Returns:
            None
        """
        if isinstance(ping_role_id, discord.Role):
            ping_role_id = ping_role_id.id
        await self.execute(
            """
            INSERT INTO tracked_guild_series (guild_id, series_id, role_id, scanlator) VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, series_id, scanlator) DO UPDATE SET role_id = $3;
            """,
            guild_id, manga_id, ping_role_id, scanlator
        )

    async def delete_manga_track_instance(self, guild_id: int, manga_id: str, scanlator: str):
        """
        Summary:
            Deletes the manga track instance from the database.

        Args:
            guild_id: int - The guild's ID
            manga_id: str - The manga's ID
            scanlator: str - The manga's scanlator

        Returns:
            None
        """
        await self.execute(
            """
            DELETE FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2 AND scanlator = $3
            """,
            guild_id, manga_id, scanlator
        )

    async def get_all_guild_tracked_manga(
            self, guild_id: int, current: str = None, autocomplete: bool = False, scanlator: str | None = None
    ) -> list[Manga]:
        """
        Summary:
            Returns a list of Manga class objects that are tracked in the guild.

        Args:
            guild_id: int - The guild's ID
            current: str - The current search query
            autocomplete: bool - Whether the function is used in an autocomplete or not
            scanlator: str - The name of the scanlator to search through

        Returns:
            list[Manga]: A list of Manga class objects that are tracked in the guild.
        """
<<<<<<< HEAD
        async with aiosqlite.connect(self.db_name) as db:
            _base = (
                "SELECT * FROM series WHERE "
                "(id, scanlator) IN (SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $1)"
            )
            if autocomplete is True:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                is_current: bool = (current or "").strip() != ""
                if scanlator is not None and is_current is True:
                    query = f"{_base} AND scanlator = $2 ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                    params = (guild_id, scanlator, current)
                elif scanlator is not None and is_current is False:
                    query = f"{_base} AND scanlator = $2 LIMIT 25;"
                    params = (guild_id, scanlator)
                elif is_current is True:
                    query = f"{_base} ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                    params = (guild_id, current)
                else:  # current False, scanlator None
                    query = f"{_base} LIMIT 25;"
                    params = (guild_id,)
            else:
                query = f"{_base};"
=======
        _base = (
            "SELECT * FROM series WHERE "
            "(id, scanlator) IN (SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $1)"
        )
        if autocomplete is True:
            is_current: bool = (current or "").strip() != ""
            if scanlator is not None and is_current is True:
                query = f"{_base} AND scanlator = $2 ORDER BY levenshtein(title, $3) DESC LIMIT 25;"
                params = (guild_id, scanlator, current)
            elif scanlator is not None and is_current is False:
                query = f"{_base} AND scanlator = $2 LIMIT 25;"
                params = (guild_id, scanlator)
            elif is_current is True:
                query = f"{_base} ORDER BY levenshtein(title, $2) DESC LIMIT 25;"
                params = (guild_id, current)
            else:  # current False, scanlator None
                query = f"{_base} LIMIT 25;"
>>>>>>> f4ba471 (fixed a few websites, added "verify_ssl" option to websites. need to find fix for the database content to keep it in line with the new website links)
                params = (guild_id,)
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
                    ]
                return []

    async def is_manga_tracked(self, manga_id: str, scanlator: str, guild_id: Optional[int] = None) -> bool:
        """
        Summary:
            Checks if a manga is tracked in the guild.

        Args:
            manga_id: str - The manga's ID
            scanlator: str - The name of the manga's scanlator
            guild_id: Optional[int] - The guild's ID

        Returns:
            bool: Whether the manga is tracked in the guild if the guild_id is provided or globally.
        """
        async with aiosqlite.connect(self.db_name) as db:
            if guild_id is not None:
                query = """
                SELECT * FROM tracked_guild_series WHERE guild_id = $1 AND series_id = $2 and scanlator = $3;
                """
                params = (guild_id, manga_id, scanlator)
            else:
                query = """
                SELECT * FROM tracked_guild_series WHERE series_id = $1 and scanlator = $2;
                """
                params = (manga_id, scanlator)
            cursor = await db.execute(query, params)
            result = await cursor.fetchone()
            return result is not None

    async def is_tracked_in_any_mutual_guild(self, header: MangaHeader, user_id: int) -> int:
        """
        Checks if the series is tracked in any of the user's mutual guilds with the bot

        Args:
            header: The series header to check for
            user_id: The user ID to check the mutual servers for

        Returns:
            The number of mutual servers the series is tracked in.
        """
        async with aiosqlite.connect(self.db_name) as db:
            user: discord.User = self.bot.get_user(user_id)
            if not user:
                return 0
            mutual_guild_ids = [f"{x.id}" for x in user.mutual_guilds] + [user_id]
            cursor = await self.execute(
                """
                SELECT COUNT(*) FROM tracked_guild_series WHERE series_id = $1 AND scanlator = $2
                AND guild_id IN ({})
                """.format(
                    ','.join(map(str, mutual_guild_ids))
                ),
                header.id, header.scanlator
            )
            return cursor.rowcount

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
            global_query = """
            SELECT * FROM series WHERE (id, scanlator) IN (
                SELECT series_id, scanlator FROM user_subs WHERE id = $1
            ) AND (id, scanlator) NOT IN (
                SELECT series_id, scanlator FROM tracked_guild_series
            );
            """
            guild_specific_query = """
            SELECT * FROM series WHERE (id, scanlator) IN (
                SELECT series_id, scanlator FROM user_subs WHERE id = $1 AND guild_id = $2
            ) AND (id, scanlator) NOT IN (
                SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $2
            );
            """
            if guild_id is not None:
                query = guild_specific_query
                params = (user_id, guild_id,)
            else:
                query = global_query
                params = (user_id,)

            async with db.execute(query, params) as cursor:
                result = await cursor.fetchall()
                if result:
                    objects = Manga.from_tuples(result)
                    return [
                        (await scanlators[x.scanlator].load_manga([x]))[0]
                        for x in objects if x.scanlator in scanlators
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
                WHERE (id, scanlator) IN (
                    SELECT series_id, scanlator FROM user_subs WHERE id = $1
                )
                AND (id, scanlator) NOT IN (
                    SELECT series_id, scanlator FROM tracked_guild_series
            """  # ) is completed below
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
            if guild_id is not None:
                query = """
                DELETE FROM user_subs WHERE id = $1 AND guild_id = $2 AND (series_id, scanlator) NOT IN (
                    SELECT series_id, scanlator FROM tracked_guild_series WHERE guild_id = $2
                );
                """
                params = (user_id, guild_id)
            else:
                query = """
                DELETE FROM user_subs WHERE id = $1 AND (series_id, scanlator) NOT IN (
                    SELECT series_id, scanlator FROM tracked_guild_series
                );"""
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

    async def get_used_scanlator_names(self, guild_id: int) -> list[str]:
        """
        Summary:
            Returns a list of scanlator names that are used in the guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            list[str]: A list of scanlator names that are used in the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT DISTINCT scanlator FROM tracked_guild_series WHERE guild_id = $1
                """,
                (guild_id,),
            )
            result = await cursor.fetchall()
            if result:
                return [row[0] for row in result]
            return []

    async def get_scanlator_channel_associations(self, guild_id: int) -> list[ScanlatorChannelAssociation]:
        """
        Summary:
            Returns a ScanlatorChannelAssociation object for the guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            list[ScanlatorChannelAssociation]: A list of ScanlatorChannelAssociation objects for the guild.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT * FROM scanlator_channel_associations WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            result = await cursor.fetchall()
            if result:
                return ScanlatorChannelAssociation.from_tuples(self.bot, result)
            return []

    async def upsert_scanlator_channel_associations(self, associations: list[ScanlatorChannelAssociation]) -> None:
        """
        Summary:
            Upserts the scanlator channel associations in the database.

        Args:
            associations: list[ScanlatorChannelAssociation] - A list of ScanlatorChannelAssociation objects

        Returns:
            None
        """
        async with aiosqlite.connect(self.db_name) as db:
            for association in associations:
                await db.execute(
                    """
                    INSERT INTO scanlator_channel_associations (guild_id, scanlator, channel_id) 
                    VALUES ($1, $2, $3) ON CONFLICT (guild_id, scanlator, channel_id) DO UPDATE SET channel_id = $3;
                    """,
                    association.to_tuple()
                )
            await db.commit()

    async def delete_scanlator_channel_association(self, guild_id: int, scanlator: str) -> None:
        """
        Deletes a scanlator channel association from the database for a guild.

        Args:
            guild_id: int - The guild's ID
            scanlator: str - The scanlator's name

        Returns:
            None
        """
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM scanlator_channel_associations WHERE guild_id = $1 AND scanlator = $2;
                """,
                (guild_id, scanlator)
            )
            await db.commit()

    async def delete_all_scanlator_channel_associations(self, guild_id: int) -> None:
        """
        Deletes all scanlator channel associations from the database for a guild.

        Args:
            guild_id: int - The guild's ID

        Returns:
            None
        """
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                DELETE FROM scanlator_channel_associations WHERE guild_id = $1;
                """,
                (guild_id,)
            )
            await db.commit()

    async def get_guild_manager_role(self, guild_id: int) -> int | None:
        """
        Summary:
            Returns the guild's manager role ID.

        Args:
            guild_id: int - The guild's ID

        Returns:
            int | None: The guild's manager role ID.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT bot_manager_role_id FROM guild_config WHERE guild_id = $1;
                """,
                (guild_id,),
            )
            result = await cursor.fetchone()
            if result:
                return result[0]

    async def set_guild_manager_role(self, guild_id: int, role_id: int) -> None:
        """
        Summary:
            Sets the guild's manager role ID.

        Args:
            guild_id: int - The guild's ID
            role_id: int - The role's ID

        Returns:
            None
        """
        await self.execute(
            """
            UPDATE guild_config SET bot_manager_role_id = $1 WHERE guild_id = $2;
            """,
            role_id, guild_id
        )
