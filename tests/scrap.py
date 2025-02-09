from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

from curl_cffi.requests import exceptions

from discord.ext import commands
from src.core.objects import Manga
from src.core.scanlators import scanlators

# Checklist:
#
done = [
    "tritinia",
    "manganato",
    "toonily",
    "mangadex",
    "flamecomics",
    "asura",
    "reaperscans",
    "comick",
    "drakescans",
    "nitroscans",
    "mangapill",
    "bato",
    "omegascans",
    ""
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

    async def fix_nightscans(self):
        new_mangas = []
        ids_to_update: list[tuple[str, str]] = []  # (old_id, new_id)

        mangas = await self.get_raw_scanaltor_manga_objs("nightscans")
        for manga in mangas:
            manga._url = manga.url.format(id="4190634673")
            try:
                new_obj = await scanlators["nightscans"].make_manga_object(manga.url, load_from_db=False)
            except exceptions.HTTPError:
                print(manga.url, manga.id)
                continue
            new_obj._chapters = new_obj.chapters[:len(manga.chapters)]
            new_obj._last_chapter = new_obj.chapters[-1]
            new_mangas.append(new_obj)
            if manga.id != new_obj.id:
                ids_to_update.append((manga.id, new_obj.id))

        for manga in new_mangas:
            await self.insert_to_db(manga)
        for old_id, new_id in ids_to_update:
            await self.replace_series_id(old_id, new_id, "nightscans", delete_old=True)
        print(f"Updated {len(new_mangas)}/{len(mangas)} in the database.")

    async def fix_resetscans(self):
        _old_id = "ceb498516cc69ffa89183d6616d0d00b78c48041068ae44a1aabf79c9c9af4dd"
        old_m = await self.get_raw_manga_obj(_old_id, "resetscans")
        await self.delete_from_db("1a1c983eb843a56fe80bc6e7fce7eebcac305257e32f5aa4dd05112ba0e633bc", "resetscans")
        new_manga = await scanlators["resetscans"].make_manga_object(
            "https://reset-scans.co/manga/the-wizard-restaurant/", load_from_db=False)
        new_manga._chapters = new_manga.chapters[:len(old_m.chapters)]
        new_manga._last_chapter = new_manga.chapters[-1]
        await self.insert_to_db(new_manga)
        await self.replace_series_id(old_m.id, new_manga.id, "resetscans", delete_old=True)

    async def fix_kaiscans(self):
        await self.delete_from_db("c524e9a0fc231cbf3b492912ef0b115f10c48668b48d84a4e9c2f634579c5e28", "kaiscans")
        old_m = await self.get_raw_manga_obj("30bb62c36f38f1ca2943c0e31816c49abcfaa94126cbb7ef3d5f6ecd00a48174",
                                             "kaiscans")
        new_m = await scanlators["kaiscans"].make_manga_object(
            "https://kaiscans.org/manga/i-was-more-overpowered-than-the-hero-so-i-hid-my-power/",
            load_from_db=False)
        new_m._chapters = new_m.chapters[:len(old_m.chapters)]
        new_m._last_chapter = new_m.chapters[-1]
        await self.insert_to_db(new_m)
        await self.replace_series_id(old_m.id, new_m.id, "kaiscans", delete_old=True)

    async def fix_zinamnga(self):
        sc = "zinmanga"
        new_mangas = []
        ids_to_update: list[tuple[str, str]] = []  # (old_id, new_id)

        old_ids_new_urls = [("455807a2c33b9175d67ebb769338d04cea228af6ed7d44180449a739e2b8354f",
                             "https://www.zinmanga.net/manga/recording-hall"),
                            ("a42198bdb0f1efe73918e24a2372d7508a5148ca75705a66b39ae6200847a133",
                             "https://www.zinmanga.net/manga/becoming-the-villain-s-family"),
                            ("f134404a4a4b914867074e2a9d3027382e92987a446c58d7604198680943111b",
                             "https://www.zinmanga.net/manga/20-year-old-college-jocks"),
                            ("3356149fb2bc17477399da11b67ace3fdc9fdff08cc0b2a58018cb6988c754d4",
                             "https://www.zinmanga.net/manga/my-father-the-possessive-demi-god"),
                            ("ebcb1933b0a75edac393d3ab24b6406e661a006a453b75de31386c814a550773",
                             "https://www.zinmanga.net/manga/i-m-a-villainess-can-i-die"),
                            ("1d377867f942c9ad51c6a3878b8899617a0aaeeaa29332fa40b1f546a9d1c483",
                             "https://www.zinmanga.net/manga/my-in-laws-areobsessed-with-me"),
                            ("3c296511abce9aa1e7fc7fa61def33cf3667528cad752e7112a29e8b820a2b71",
                             "https://www.zinmanga.net/manga/why-are-you-obsessed-with-your-fake-wife"),
                            ("292db03d53f8b213142175e117a7a9b828c3cbaac0965c6f6c6d729387c3ac9f",
                             "https://www.zinmanga.net/manga/the-max-level-players-100th-regression"),
                            ("71a5f9152461c3d35944dadbcc0cd42aff2b16d9edd876c53a70d6cedbe8c583",
                             "https://www.zinmanga.net/manga/i-became-the-young-villains-sister-in-law"),
                            ("a789d58565659d5e05a565728ca0c3a85dd55c8548ef4582b30ed45a6c1b6c8c",
                             "https://www.zinmanga.net/manga/the-dungeons-time-bound-s-rank-beauty"),
                            ("808b0b3dc15b76393635746f5f4f8bdcbee17de3ea4ddc83bc648a2c7132f9f8",
                             "https://www.zinmanga.net/manga/beloved-in-laws"),
                            ("802859d19a4eddc59a550089a7e10a5448f9d780821dc907c0af004ae12ae6d8",
                             "https://www.zinmanga.net/manga/a-fortune-telling-princess"),
                            ("a2f4c5df50206d97f1793d1c8e8abbd572dc445df8a8c6176180b3d18ed3e124",
                             "https://www.zinmanga.net/manga/a-stepmother-s-marchen"),
                            ("513d5d371f4ecd5e9741f21343e0d2470b39411baddd2e3c59f25bd4d51c4080",
                             "https://www.zinmanga.net/manga/the-s-class-hunter-doesnt-want-to-be-a-villainous-princess"),
                            ("72a2882ccba7bb7c6a94b89000504198090729d61625e076d5894e32d9ad6e92",
                             "https://www.zinmanga.net/manga/how-to-reject-my-obsessive-ex-husband"),
                            ("578c1935a4acf7d246c6a849f6eefc831e3ddc789647f64feba7cd1aa7441dd5",
                             "https://www.zinmanga.net/manga/becoming-the-obsessive-male-leads-ex-wife"),
                            ("9a0f8559ff51592582b2ebd03cc5ff87283be03072f754bb5a70c995cda54b37",
                             "https://www.zinmanga.net/manga/the-s-class-little-princess-is-too-strong"),
                            ("9331a739e40f60f1d7925ba6121553594b09156a6e8913bc5b9dda7e68f17fe1",
                             "https://www.zinmanga.net/manga/the-adopted-daughter-in-law-wants-to-leave"),
                            ("384a4e3454ecdc9d0f77039faec069cdfcca386dfd64f0837d8b5864f1f24d5e",
                             "https://www.zinmanga.net/manga/i-tamed-my-ex-husbands-mad-dog"),
                            ("7cd382931413ebaf3da82cb22b467b192f50dc197b0824f48fc74d805c125abc",
                             "https://www.zinmanga.net/manga/when-i-quit-being-a-wicked-mother-in-law-everyone-became-obsessed-with-me"),
                            ("08407ffb7639bffafa50de8a71b0f4311d63d6847fabd085243ff363020cce46",
                             "https://www.zinmanga.net/manga/daisy-how-to-become-the-duke-s-fiancee"),
                            ("113c467a3b52a4959142c42b628257f4b51dc6cb34f056041d152302f61a710a",
                             "https://www.zinmanga.net/manga/duchesss-lo-fi-coffeehouse"),
                            ]
        to_delete = ["8473635355dd2d4fb4f08131e49b17679b8c26f3c0b8ad763d8b19c5c454549e",
                     "983971c6b54d9adafd28060f1c50e40431866608c9bcc1ba8782a94691e23bc0"]
        for _id in to_delete:
            await self.delete_from_db(_id, sc)
        for old_id, new_url in old_ids_new_urls:
            new_obj = await scanlators[sc].make_manga_object(new_url, load_from_db=False)
            await self.insert_to_db(new_obj)
            await self.replace_series_id(old_id, new_obj.id, sc, delete_old=True)

        mangas = await self.get_raw_scanaltor_manga_objs(sc)

        for i, manga in enumerate(mangas):
            print(str(i + len(old_ids_new_urls) + len(to_delete)) + ":", manga.url)
            if "www." not in manga.url:
                manga._url = manga.url.replace("zinmanga.net", "www.zinmanga.net")

            new_obj = await scanlators[sc].make_manga_object(manga.url, load_from_db=False)
            new_obj._chapters = new_obj.chapters[:len(manga.chapters)]
            new_obj._last_chapter = new_obj.chapters[-1]
            new_mangas.append(new_obj)
            if manga.id != new_obj.id:
                ids_to_update.append((manga.id, new_obj.id))
        for manga in new_mangas:
            await self.insert_to_db(manga)
        for old_id, new_id in ids_to_update:
            await self.replace_series_id(old_id, new_id, sc, delete_old=True)
        print(f"Updated {len(new_mangas)}/{len(mangas)} in the database.")

    async def fix_kunmanga(self):
        sc = "kunmanga"
        mangas = await self.get_raw_scanaltor_manga_objs(sc)
        total_fixes = 0
        for i, manga in enumerate(mangas):
            chapter_links = []
            new_chapters = []
            print(str(i) + ":", manga.url)
            for _ch in manga.chapters:
                if _ch.url in chapter_links:
                    continue
                chapter_links.append(_ch.url)
                new_chapters.append(_ch)
            if len(new_chapters) != len(manga.chapters):
                for i, _ch in enumerate(new_chapters):
                    _ch.index = i + 1
                manga._chapters = new_chapters
                manga._last_chapter = new_chapters[-1]
                await self.insert_to_db(manga)
                print(f"Fixed: {total_fixes + 1}", manga.url)
                total_fixes += 1

        print(f"Fixed {total_fixes} in the database for kunmanga.")

    async def fix_hivescans(self):
        sc = "hivescans"
        new_mangas = []
        ids_to_update: list[tuple[str, str]] = []  # (old_id, new_id)

        for old_id, new_url in [("c05c5acfaeed85d9bdb1413822d778395bf4b4d754bfea2ad8a7ff5b54b0bc74",
                                 "https://hivetoon.com/series/past-life-regressor-2022"), ]:
            new_obj = await scanlators[sc].make_manga_object(new_url, load_from_db=False)
            await self.insert_to_db(new_obj)
            await self.replace_series_id(old_id, new_obj.id, sc, delete_old=True)

        mangas = await self.get_raw_scanaltor_manga_objs(sc)
        for manga in mangas:
            manga._url = manga.url.replace("void-scans.com/manga", "hivetoon.com/series")
            try:
                new_obj = await scanlators[sc].make_manga_object(manga.url, load_from_db=False)
            except exceptions.HTTPError:
                print(manga.url, manga.id)
                continue
            new_obj._chapters = new_obj.chapters[:len(manga.chapters)]
            new_obj._last_chapter = new_obj.chapters[-1]
            new_mangas.append(new_obj)
            if manga.id != new_obj.id:
                ids_to_update.append((manga.id, new_obj.id))

        for manga in new_mangas:
            await self.insert_to_db(manga)
        for old_id, new_id in ids_to_update:
            await self.replace_series_id(old_id, new_id, sc, delete_old=True)

        print(f"Updated {len(new_mangas)}/{len(mangas)} in the database.")

    async def delete_old_scan_configs(self):
        deleted_scanlators = 0
        configs = await self.bot.db.execute("SELECT scanlator from main.scanlators_config")
        for config in configs:
            c = config[0]
            if c not in self.bot._all_scanners:
                await self.bot.db.execute("DELETE FROM main.scanlators_config WHERE scanlator = $1", c)
                deleted_scanlators += 1
        print(f"Deleted {deleted_scanlators} old scanlators from the database.")

    async def fix_topreadmanhwa(self):
        sc = "topreadmanhwa"
        to_delete = ["9bc36ce558cad2711f6f460ccf100452f9b48f7691f19c9d6fcfb97cbad2b928",
                     "55af4a7a9e04e2bf0ab058b4c932d44d22c7f7d8420b723d4847c04b0c39a4c5",
                     '2de2bca4cf120d266dae0ded046525a30a576cde4cc964b78643a61101f56614',
                     '887a951e8e09957cd59319ca7cc6ab7920455166658ab775b0077e7a3b062c07',
                     'f81fca9915cfbeac14966da1f533e665b8c34d3714bdfdcc5318ef860788d2e0',
                     '0c31121d423d74f57e664d8b383897a1244bc4dfa386e39ab990ae523ad364d2',
                     '40e28044e8a242105e62f78c3efd7f22843a21a9f4356ddfe5a7d52cf8dd4411',
                     '253bd3b780f05630b74b0b755b8631aabf3e87c66b3b8f69907564a114fd3d73',
                     '2cb24d725a1f340ad05b4ffd5a61da184a082f4bb0d0da8c633a974766ab07b7',
                     '2d20d93d205ad3e782363876b4ef71f91eb9b7fddb891144724144e253745b9b',
                     'f9566527be1f7514aa6cbc42e0163a5bd2ef69c419bc4efd83daadcbf66521be',
                     '07b322b31dcfa4fd84e0f6dad60d726095948b5e3d1c13fcc2225d60d4fb934b',
                     'b2d8a508a67593379635607e85ef94d53dfd6193b376c30a9317884f7afca034',
                     '31c80bcc7e0cfcdcaefc143ff28fc5bd5d5ca8bee3f1acb7c3c4eea19c772a20',
                     '5bdc937d75ccf7811ce7997c247b949522100c56529dbe8f06c65f9f53210e75',
                     '83bf5a903f29fb00c41745360dad6dc9a72cc562a25cb9c8c64fd798cd97ce2c',
                     '32e54c5b6363c1f3d5f4c1f446f686f93749c0102f3d32dbee7ce7b3a49dea53',
                     'b38913d96637402c31b7842dac32695d45859673bd93fd925fdf34112c6bd1d0',
                     '1e4f7932f63f243ca7329c5da9558a682d1ea633ccf0b10002a95be4208c4b48',
                     '9f7a89a896c0e1e341883d1192cfddb5cd0698e1e056ca685f08fe2fbd49f120',
                     'e345f4b025c23caecf25f9569481640e349ea4c0122dcdf5a6b15d7a7c52650d',
                     'd8df89406ff66bf930c6ef9e2f65f2eee192f1158d7c2652f2e75c9279716300',
                     'b1ffd5e38277d1b7a0be45a07b8897319bfcc73798d57bd2480a5868b2203d53',
                     '8edc290183959836c612b4c9db667e6b78fe28dc10e51a28b42187c736517b53',
                     'b8c3fcd9df8dd489d8e621e8d9797b3332017f7319f79cda589e82b91ef7cda1',
                     'e0ed15887046e5497fba5c9c0c2ba2b645b30d936b568490c0eac39eaa9f7a7d',
                     '96f2b940bb84741a862bc4bece3188512d842e36d92be690ab11ea6778595497',
                     '169ad77a7afb11a91fe0140a37116f8e7dff96ba5d91674fe1dde96590c74197',
                     '6b1d2b5c9a4535f2868802fd8e8c322cec9c63ac3841cc772cca08732540861c',
                     '74f1d3e9e20a1a99e0d7cb6aa869b5e77e996f812ae8e85a9a84bb658ff46075',
                     'c9b5fab4817189ee1eeb60347bc3ee7ff838ccf40139d5a2691c91d32ab96d4c',
                     '7ca71ba42bafd70bfc38d2bc3e696906c43707392414a64d55b8199b1aea90a2',
                     '77d89596c4b3f290c1428228e5be9aec2e740586f4c0f656fa10a12078dcfe62',
                     '84bebae3e7068fc40cf8a4b1b5cb11c77d2eaa2487cb6326493605a7623086c4',
                     '374f28974bd4bd2eee8baf9136ef199af88bf8bd985bb9beba55617c29bf3aef',
                     '6d17ec514e0e1ee2caf969b4c73fb90813295a7d89d1b4d7d3bf73a498d498f2',
                     '78d3bd53345d14649d81f61b76f0ca8e162753af3019002f8ebffca157cb631a',
                     'aef8eced2fb5aae88057ddec0a5e0298f7fd1b02a044b41d81ac006ef07e4c8b',
                     '774ba022c37a696eb44fb369860e803816e8cdea88cba7b8b4e0b7baaf648943',
                     '4c44c0445b82c377369e6eee7aa6732cc66d7abe443ab09f4d457d1f16543733',
                     'f4c600d6caaee91102b64f60d134f107327e14d77db4604fbfe59d34229f472a',
                     '49c3233cc0e55e9553d081834b7b6a50fc2a9ff815e2a47ec2c54ee92d3080d7',
                     'fce740f687404660581ecce85b5c5e1ef1880b1e870dbd5849b57523da94123d']
        for _id in to_delete:
            await self.delete_from_db(_id, sc)

    async def fix_flamecomics(self):
        sc = "flamecomics"

        for old_id, new_url in [
            ("36822f7ed55461a795ca7235c714ae122fc6d919e9d08008ac4206693391b10a",
             "https://flamecomics.xyz/series/95"),
            ("a0694041d0bc4cd09b095c5db5479ed1fea63c140b013d471a9bcbb4acedc98c",
             "https://flamecomics.xyz/series/117"),
            ("b45c3b6271a16ee3216d19f516ee9d984c92cb3748adf7d72e8b304411a96d4b",
             "https://flamecomics.xyz/series/100"),
            ("921ee30ae4b7ea2ebae98443f374ab026cea0bf6750515cd9a6de5129ddb4812",
             "https://flamecomics.xyz/series/49"),
            ("1f05abc72cc2d8b718b5b6269b26f5c68fc40def806036af5c13c98e712e94bb",
             "https://flamecomics.xyz/series/2"),
        ]:
            new_obj = await scanlators[sc].make_manga_object(new_url, load_from_db=False)
            await self.insert_to_db(new_obj)
            await self.replace_series_id(old_id, new_obj.id, sc, delete_old=True)

    async def fix_manganato(self):
        sc = "manganato"

        for old_id, new_url in [
            ("dm981095",
             "https://chapmanganato.to/manga-lb988758"),
        ]:
            new_obj = await scanlators[sc].make_manga_object(new_url, load_from_db=False)
            await self.insert_to_db(new_obj)
            await self.replace_series_id(old_id, new_obj.id, sc, delete_old=True)

    async def fix_drakescans(self):
        sc = "drakescans"
        to_delete = ["0b4004621d2683a800e01794610a309fe62c3079f2c0bb0a1fca47813430f16a", ]
        for _id in to_delete:
            await self.delete_from_db(_id, sc)

    async def fix_asura(self):
        sc = "asura"
        ids_to_update: list[tuple[str, str]] = [
            ("8ba409faed7e7767515ed84a3c86e80247e3f72cc306336678e1bc582b9abdfa",
             "https://asuracomic.net/series/warrior-high-school-dungeon-raid-department-73d230a5"),
            ("e6e123aa376ea7e51e9f427252d7cc77b67e57f843055b42d7f862f895ce5cd7",
             "https://asuracomic.net/series/star-embracing-swordmaster-fcff1f5f"),
        ]  # (old_id, new_id)
        chapter_limits = []
        for old_id, _ in ids_to_update:
            m = await self.get_raw_manga_obj(old_id, sc)
            chapter_limits.append(len(m.chapters))

        for old_id, new_url in ids_to_update:
            new_obj = await scanlators[sc].make_manga_object(new_url, load_from_db=False)
            new_obj._chapters = new_obj.chapters[:chapter_limits.pop(0)]
            new_obj._last_chapter = new_obj.chapters[-1]
            unld_m = await scanlators[sc].unload_manga([new_obj])
            unld_m = unld_m[0]
            await self.insert_to_db(unld_m)
            await self.replace_series_id(old_id, new_obj.id, sc, delete_old=False)

    async def cog_load(self) -> None:
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
        # await self.delete_old_scan_configs()
        # await self.enable_all_scanlators()
        # await self.fix_nightscans()
        # await self.fix_resetscans()
        # await self.fix_kaiscans()
        # await self.fix_zinamnga()
        # await self.fix_kunmanga()
        # await self.fix_hivescans()
        await self.fix_topreadmanhwa()
        # await self.fix_manganato()
        # await self.fix_flamecomics()
        # await self.fix_drakescans()
        # await self.fix_asura()


async def setup(bot: "MangaClient"):
    await bot.add_cog(FixDbCog(bot))
