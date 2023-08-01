from __future__ import annotations

import os
from datetime import datetime
from typing import Any, List, TYPE_CHECKING

import aiosqlite
from fuzzywuzzy import fuzz

if TYPE_CHECKING:
    from .bot import MangaClient

from src.core.objects import GuildSettings, Manga, Bookmark, Chapter
from io import BytesIO
import pandas as pd
import sqlite3
from src.core.errors import DatabaseError


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
                    
                    last_chapter TEXT NOT NULL,
                    available_chapters TEXT NOT NULL,
                    
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
                    UNIQUE (id, series_id) ON CONFLICT IGNORE
                )
                """
            )

            await db.execute(
                # user_id: the discord ID of the user the bookmark belongs to
                # series_id: the ID of the series from the series table
                # last_read_chapter: the last chapter the user read
                # guild_id: the discord guild the user bookmarked the manga from
                # last_updated_ts: the timestamp of the last time the bookmark was updated by the user
                # user_created: whether the bookmark was created by the user or by the bot
                """
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id INTEGER NOT NULL,
                    series_id TEXT NOT NULL,
                    last_read_chapter TEXT DEFAULT NULL,
                    guild_id INTEGER NOT NULL,
                    last_updated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_created BOOLEAN NOT NULL DEFAULT false,
                    
                    FOREIGN KEY (series_id) REFERENCES series (id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (guild_id) REFERENCES config (guild_id),
                    UNIQUE (user_id, series_id) ON CONFLICT IGNORE
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
                CREATE TABLE IF NOT EXISTS scanlators_config (
                    scanlator TEXT PRIMARY KEY NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1
                );
                """
            )
            await db.commit()

    async def execute(self, query: str, *args) -> Any:
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(query, args) as cursor:
                result = await cursor.fetchall()
                await db.commit()
                return result

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
            await db.execute(
                """
                INSERT INTO series (id, human_name, url, synopsis, series_cover_url, last_chapter, available_chapters, completed, 
                scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id) DO NOTHING;
                """,
                (manga_obj.to_tuple()),
            )

            await db.commit()

    async def upsert_bookmark(self, bookmark: Bookmark) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT INTO series (id, human_name, url, synopsis, series_cover_url, last_chapter, available_chapters, completed, 
                scanlator) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT(id) DO NOTHING;
                """,
                (bookmark.manga.to_tuple()),
            )

            await db.execute(
                """
                INSERT INTO bookmarks (
                    user_id,
                    series_id, 
                    last_read_chapter,
                    guild_id,
                    last_updated_ts,
                    user_created
                    ) 
                VALUES ($1, $2, $3, $4, $5, $6) 
                ON CONFLICT(user_id, series_id) DO 
                UPDATE SET last_read_chapter=$3, last_updated_ts=$5, user_created=$6;
                """,
                (bookmark.to_tuple()),
            )
            await db.commit()
            return True

    async def subscribe_user(self, user_id: int, guild_id: int, series_id: int) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            # INSERT OR IGNORE INTO users (id, series_id, guild_id) VALUES ($1, $2, $3);
            await db.execute(
                """
                INSERT INTO users (id, series_id, guild_id) VALUES ($1, $2, $3) ON CONFLICT(id, series_id) DO NOTHING;
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
                SELECT * FROM users WHERE id = $1 AND series_id = $2;
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
                INSERT INTO bookmarks (user_id, series_id, last_read_chapter, guild_id, last_updated_ts, user_created) 
                VALUES ($1, $2, $3, $4, $5, false) 
                ON CONFLICT(user_id, series_id) 
                DO UPDATE SET last_read_chapter = $3, last_updated_ts = $5;
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
                INSERT INTO config (guild_id, channel_id, updates_role_id, webhook_url) VALUES ($1, $2, $3, $4
                ) ON CONFLICT(guild_id) DO UPDATE SET channel_id = $2, updates_role_id = $3, webhook_url = $4 
                WHERE guild_id = $1;
                """,
                settings.to_tuple(),
            )

            await db.commit()

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
                    SELECT * FROM series WHERE series.id NOT IN (SELECT series_id FROM users)
                    AND series.id NOT IN (SELECT series_id FROM bookmarks);
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return Manga.from_tuples(result)
                return None

    async def get_manga_guild_ids(self, manga_id: str | int) -> list[int]:
        """
        Summary:
            Returns a list of guild ids that has subscribed to the manga.

        Parameters:
            manga_id (str|int): The id of the manga.

        Returns:
            list[int]: list of guild ids that has subscribed to the manga.
        """
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute(
                    """
                    SELECT guild_id FROM users WHERE series_id = $1;
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
                    completed = 0 AND id IN (SELECT series_id FROM users UNION SELECT series_id FROM bookmarks);
                    """
            ) as cursor:
                result = await cursor.fetchall()
                if result:
                    return Manga.from_tuples(result)
                return None

    async def get_user_bookmark(self, user_id: int, series_id: str) -> Bookmark | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT
                    b.user_id,
                    b.series_id,
                    b.last_read_chapter,
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
                    b.last_read_chapter,
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
            # INNER JOIN users
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
            if current is not None:
                await db.create_function("levenshtein", 2, _levenshtein_distance)
                cursor = await db.execute(
                    """
                    SELECT id, human_name FROM series
                    WHERE series.id IN (SELECT series_id FROM bookmarks WHERE user_id = $1)
                    ORDER BY levenshtein(human_name, $2) DESC
                    LIMIT 25;
                    """,
                    (user_id, current),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, human_name 
                    FROM series 
                    WHERE series.id IN (SELECT series_id FROM bookmarks WHERE user_id = $1);
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
                if current is not None:
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
                    SELECT * FROM config WHERE guild_id = ?;
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
                    SELECT * FROM config WHERE guild_id IN ({});
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
                    return Manga.from_tuple(result)

    async def get_all_series(self, current: str = None, *, autocomplete: bool = False) -> list[Manga] | None:
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
                        return Manga.from_tuples(result)
        else:
            async with aiosqlite.connect(self.db_name) as db:
                async with db.execute(
                        """
                        SELECT * FROM series;
                        """
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
                UPDATE series SET last_chapter = $1, series_cover_url = $2, available_chapters = $3 WHERE id = $4;
                """,
                (manga.last_chapter.to_json(), manga.cover_url, manga.chapters_to_text(), manga.id),
            )
            if result.rowcount < 1:
                raise ValueError(f"No series with ID {manga.id} was found.")
            await db.commit()

    async def update_last_read_chapter(self, user_id: int, series_id: str, last_read_chapter: Chapter) -> None:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                UPDATE bookmarks SET last_read_chapter = $1, last_updated_ts = $2 WHERE user_id = $3 AND series_id = $4;
                """,
                (last_read_chapter.to_json(), datetime.utcnow().timestamp(), user_id, series_id),
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
                    SELECT series_id FROM users
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
                DELETE FROM users WHERE id = $1 and series_id = $2;
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
