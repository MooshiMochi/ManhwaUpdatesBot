import re


class Emotes:
    warning = "⚠️"


class RegExpressions:
    chapter_num_from_url = re.compile(r"(\d+([.]\d+)?)/?$")
    toonily_url = re.compile(
        r"(https?://)?(www\.)?toonily.com/webtoon/([a-zA-Z0-9-]+)(/.*)?"
    )
    manganato_url = re.compile(
        r"(https?://)?(www\.)?(chap)?manganato.com/manga-([a-zA-Z0-9-]+)(/.*)?"
    )
    tritinia_url = re.compile(
        r"(https?://)?(www\.)?tritinia.org/manga/([a-zA-Z0-9-]+)(/.*)?"
    )
