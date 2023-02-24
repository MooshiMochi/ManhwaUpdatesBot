from src.core.scanlationClasses import *

from .static import RegExpressions


def get_manga_scanlation_class(url: str = None, key: str = None) -> ABCScan | None:
    if url is None and key is None:
        raise ValueError("Either URL or key must be provided.")

    d: dict[str, ABCScan] = {
        "toonily": Toonily,
        "manganato": Manganato,
        "tritinia": TritiniaScans,
        "mangadex": MangaDex,
        "chapmanganato": Manganato,
    }

    if key is not None:
        if existing_class := d.get(key):
            return existing_class

    for name, obj in RegExpressions.__dict__.items():
        if isinstance(obj, re.Pattern) and name.count("_") == 1:
            if obj.match(url):
                return d[name.split("_")[0]]
