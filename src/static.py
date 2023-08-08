import re


class Emotes:
    warning = "⚠️"


class Constants:
    no_img_available_url = "https://st4.depositphotos.com/14953852/22772/v/600/depositphotos_227725020-stock" \
                           "-illustration-image-available-icon-flat-vector.jpg"

    @staticmethod
    def default_headers() -> dict:
        """
        Must set the following headers:
            :Authority:
            :Path:
            Refer
        If not set, you should remove them from the dict with .pop(key, default) method.
        """  # noqa
        return {
            ":Authority": "",
            ":Method": "GET",
            ":Path": "",
            ":Scheme": "https",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
                      "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",

            "Content-Length": "0",
            "Origin": "",
            "Connection": "keep-alive",
            "Host": "",
            "Pragma": "no-cache",

            "Referer": "",
            "Sec-Ch-Ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Opera GX";v="100"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/114.0.0.0 Safari/537.36 OPR/100.0.0.0",
            "X-Requested-With": "XMLHttpRequest",
        }.copy()


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
        r"(?:https?://)?(?:www\.)?toonily\.com/webtoon/(?P<url_name>[a-zA-Z0-9-]+)(?:/.*)?"
    )
    manganato_url = re.compile(
        r"(?:https?://)?(?:www\.)?(?:chap)?manganato\.com/manga-(?P<id>[a-zA-Z0-9]+)(?:/.*)?"
    )
    tritinia_url = re.compile(
        r"(?:https?://)?(?:www\.)?tritinia\.org/manga/(?P<url_name>[a-zA-Z0-9-]+)(?:/.*)?"
    )
    mangadex_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangadex\.org/title/(?P<id>[a-zA-Z0-9-]+)(?:/.*)?"
    )
    flamescans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?flamescans\.org/(?:series/)?(?:\d+-)?(?P<url_name>[\w-]+?)(?:-chapter-[\d-]+)?/?("
        r"?:/.*)?$"
    )

    asura_url = re.compile(
        r"(?:https?://)?(?:www\.)?asura\.gg/(?:manga/)?(?:\d+-)?(?P<url_name>[\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    reaperscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?reaperscans\.com/comics/(?P<id>[0-9]+)-(?P<url_name>[a-zA-Z0-9-]+)(?:/.*)?"
    )

    aquamanga_url = re.compile(
        r"(?:https?://)?(?:www\.)?aquamanga\.com/read/(?P<url_name>[a-zA-Z0-9-]+)(?:/.*)?"
    )

    anigliscans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?anigliscans\.com/(?:series/)?(?P<url_name>[\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    comick_url = re.compile(
        r"(?:https?://)?(?:www\.)?comick\.app/comic/(?P<url_name>[a-zA-Z0-9-]+)(?:\??/.*)?"
    )

    voidscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?void-scans\.com/(?:manga/)?(?P<url_name>[\w-]+?)(?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    luminousscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?luminousscans\.com/series/(?P<id>\d+)-(?P<url_name>[\w-]+)"
    )

    leviatanscans_url = re.compile(
        r"(?:https?://)?(?:en\.)?leviatanscans\.com/manga/(?P<url_name>[\w-]+)(?:/.*)?"
    )

    drakescans_url = re.compile(
        r"(?:https?://)?(?:www\.)?drakescans\.com/series/(?P<url_name>[\w-]+)(?:/.*)?"
    )

    mangabaz_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangabaz\.net/mangas/(?P<url_name>[\w-]+)(?:/.*)?"
    )

    mangapill_url = re.compile(
        # r"(?:https?://)?(?:www\.)?mangapill\.com/manga/(\d+)/([\w-]+)(?:/.*)?"
        r"(?:https?://)?(?:www\.)?mangapill\.com/(?:manga|chapters)/?(?P<id>\d+)(?:-\d+)?/(?P<url_name>[\w-]+?)("
        r"?:-chapter-[\d-]+)?/?(?:/.*)?$"
    )

    bato_url = re.compile(
        r"(?:https?://)?(?:www\.)?bato\.to/series/(?P<id>\d+)/(?P<url_name>[\w-]+)(?:/.*)?"
    )

    omegascans_url = re.compile(
        r"(?:https?://)?(?:www\.)?omegascans\.org/series/(?P<url_name>[\w-]+)(?:/.*)?"
    )
