import re


class Emotes:
    warning = "⚠️"


class Constants:
    no_img_available_url = "https://st4.depositphotos.com/14953852/22772/v/600/depositphotos_227725020-stock" \
                           "-illustration-image-available-icon-flat-vector.jpg"


class EMPTY:
    """
    A class that represents an empty object.
    """
    pass


class ScanlatorsRequiringUserAgent:
    """
    A class that contains a list of scanlators that require a user-agent.
    """
    scanlators = [
        "anigliscans",
        "aquamanga",
        "toonily",
    ]


class RegExpressions:
    chapter_num_from_url = re.compile(r"(\d+([.]\d+)?)/?$")
    url = re.compile(r"https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(%[0-9a-fA-F][0-9a-fA-F]))+")
    toonily_url = re.compile(
        r"(?:https?://)?(?:www\.)?toonily\.com/webtoon/([a-zA-Z0-9-]+)(?:/.*)?"
    )
    manganato_url = re.compile(
        r"(?:https?://)?(?:www\.)?(?:chap)?manganato\.com/manga-([a-zA-Z0-9]+)(?:/.*)?"
    )
    tritinia_url = re.compile(
        r"(?:https?://)?(?:www\.)?tritinia\.org/manga/([a-zA-Z0-9-]+)(?:/.*)?"
    )
    mangadex_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangadex\.org/title/([a-zA-Z0-9-]+)(?:/.*)?"
    )
    flamescans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?flamescans\.org/(?:series/)?(?:\d+-)?([\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    asurascans_url = re.compile(
        r"(?:https?://)?(?:www\.)?asurascans\.com/manga/(?:\d+-)?([a-zA-Z0-9-]+)(?:/.*)?"
    )

    reaperscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?reaperscans\.com/comics/([0-9]+)-([a-zA-Z0-9-]+)(?:/.*)?"
    )

    aquamanga_url = re.compile(
        r"(?:https?://)?(?:www\.)?aquamanga\.com/read/([a-zA-Z0-9-]+)(?:/.*)?"
    )

    anigliscans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?anigliscans\.com/(?:series/)?([\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    comick_url = re.compile(
        r"(?:https?://)?(?:www\.)?comick\.app/comic/([a-zA-Z0-9-]+)(?:\??/.*)?"
    )

    voidscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?void-scans\.com/(?:manga/)?([\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    luminousscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?luminousscans\.com/series/(\d+)-([\w-]+)"
    )

    leviatanscans_url = re.compile(
        r"(?:https?://)?(?:en\.)?leviatanscans\.com/manga/([\w-]+)(?:/.*)?"
    )

    drakescans_url = re.compile(
        r"(?:https?://)?(?:www\.)?drakescans\.com/series/([\w-]+)(?:/.*)?"
    )

    mangabaz_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangabaz\.net/mangas/([\w-]+)(?:/.*)?"
    )

    mangapill_url = re.compile(
        # r"(?:https?://)?(?:www\.)?mangapill\.com/manga/(\d+)/([\w-]+)(?:/.*)?"
        r"(?:https?://)?(?:www\.)?mangapill\.com/(?:manga|chapters)/?(\d+)(?:-\d+)?/([\w-]+?)(?:-chapter-["
        r"\d-]+)?/?(?:/.*)?$"
    )

    bato_url = re.compile(
        r"(?:https?://)?(?:www\.)?bato\.to/series/(\d+)/([\w-]+)(?:/.*)?"
    )

    omegascans_url = re.compile(
        r"(?:https?://)?(?:www\.)?omegascans\.org/series/([\w-]+)(?:/.*)?"
    )
