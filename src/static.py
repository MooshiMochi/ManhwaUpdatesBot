import re


class Emotes:
    warning = "⚠️"


class RegExpressions:
    chapter_num_from_url = re.compile(r"(\d+([.]\d+)?)/?$")
    toonily_url = re.compile(
        r"(?:https?://)?(?:www\.)?toonily.com/webtoon/([a-zA-Z0-9-]+)(/.*)?"
    )
    manganato_url = re.compile(
        r"(?:https?://)?(?:www\.)?(?:chap)?manganato.com/manga-([a-zA-Z0-9]+)(?:/.*)?"
    )
    tritinia_url = re.compile(
        r"(?:https?://)?(?:www\.)?tritinia.org/manga/([a-zA-Z0-9-]+)(/.*)?"
    )
    mangadex_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangadex.org/title/([a-zA-Z0-9-]+)(/.*)?"
    )
    flamescans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?flamescans\.org/(?:series/)?(?:\d+-)?([\w-]+?)(?:-chapter-[\d-]+)?/?(/.*)?$"
    )

    asurascans_url = re.compile(
        r"(?:https?://)?(?:www\.)?asurascans.com/manga/(?:\d+-)?([a-zA-Z0-9-]+)(/.*)?"
    )

    reaperscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?reaperscans.com/comics/([0-9]+)-([a-zA-Z0-9-]+)(/.*)?"
    )

    aquamanga_url = re.compile(
        r"(?:https?://)?(?:www\.)?aquamanga.com/read/([a-zA-Z0-9-]+)(/.*)?"
    )

    aniglisscans_url = re.compile(
        r"^(?:https?://)?(?:www\.)?anigliscans\.com/(?:series/)?([\w-]+?)(?:-chapter-[\d-]+)?/?(/.*)?$"
    )

    comick_url = re.compile(
        r"(?:https?://)?(?:www\.)?comick.app/comic/([a-zA-Z0-9-]+)(?:\??/.*)?"
    )

    voidscans_url = re.compile(
        r"(?:https?://)?(?:www\.)?void-scans\.com/(?:manga/)?([\w-]+?)(?:-chapter-[\d-]+)?/?(/.*)?$"
    )
