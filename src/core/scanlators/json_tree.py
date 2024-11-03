import re
from typing import Any, Literal, Optional

from curl_cffi.requests import Cookies

__all__ = ("JSONTree",)


class _FormatUrlsProperties:
    def __init__(self, **format_urls_dict):
        self.manga: str = format_urls_dict["manga"]
        self.ajax: Optional[str] = format_urls_dict.get("ajax")  # optional


class MissingIDConnector:
    def __init__(self, **missing_id_connector_dict):
        self.exists: bool = missing_id_connector_dict is not None and missing_id_connector_dict != {}
        self.char: str | None = missing_id_connector_dict.get("char")
        self.before_id: bool = missing_id_connector_dict.get("before_id", False)


class _Properties:
    def __init__(self, **properties_dict):
        self.base_url: str = properties_dict["base_url"]
        self.icon_url: str = properties_dict["icon_url"]
        self.format_urls: _FormatUrlsProperties = _FormatUrlsProperties(**properties_dict["format_urls"])
        self.latest_updates_url: str = properties_dict["latest_updates_url"]
        self.dynamic_url: bool = properties_dict["dynamicURL"]
        self.time_formats: list[str] = properties_dict.get("time_formats")
        self.no_status: bool = properties_dict.get("no_status", False)
        self.requires_update_embed = properties_dict.get("requires_update_embed", False),
        self.can_render_cover = properties_dict.get("can_render_cover", True)
        self.missing_id_connector = MissingIDConnector(**properties_dict.get("missing_id_connector", {}))
        self.url_chapter_prefix = properties_dict.get("url_chapter_prefix")
        self.chapter_regex = properties_dict.get("chapter_regex", None)
        if self.chapter_regex is not None:
            self.chapter_regex = re.compile(self.chapter_regex)


class _CustomHeaders:
    def __init__(self, **custom_headers_dict):
        cookies_list = custom_headers_dict.pop("Cookies", None)
        self.headers: dict[str, str] = custom_headers_dict

        self.cookies: Cookies | None = None
        if cookies_list:
            self.cookies = Cookies()
            for cookie in cookies_list:
                self.cookies.set(**cookie)


class _FrontPageSelectors:
    def __init__(self, **fp_selectors_dict):
        self.container: str = fp_selectors_dict["container"]
        self.chapters: dict = fp_selectors_dict.get("chapters")
        self.title: str = fp_selectors_dict["title"]
        self.url: str = fp_selectors_dict["url"]
        self.cover: str = fp_selectors_dict.get("cover")


class _Selectors:
    def __init__(self, **selectors_dict):
        self.title: list[str] = selectors_dict["title"]
        self.synopsis: str = selectors_dict["synopsis"]
        self.cover: list[str] = selectors_dict["cover"]
        self.chapters: dict[str, str] = selectors_dict["chapters"]
        self.status: list[str] = selectors_dict["status"]
        self.front_page: _FrontPageSelectors = _FrontPageSelectors(**selectors_dict["front_page"])
        self.search: _FrontPageSelectors = _FrontPageSelectors(**selectors_dict["search"])
        self.unwanted_tags: list[str] = selectors_dict["unwanted_tags"]


class _QueryParsing:
    def __init__(self, **parsing_dict):
        self.encoding: Literal["url", "raw", None] = parsing_dict["encoding"]
        self.regex: list[dict[str, str]] = parsing_dict.get("regex", [])


class _SearchProperties:
    def __init__(self, **search_dict):
        self.url: str = search_dict["url"]
        self.search_param_name: str = search_dict.get("search_param_name")
        self.extra_params: dict[str, Any] = search_dict["extra_params"]
        self.as_type: Literal["param", "path"] = search_dict["as_type"]
        self.query_parsing: _QueryParsing = _QueryParsing(**search_dict["query_parsing"])
        self.request_method: Literal["GET", "POST"] = search_dict["request_method"]


class JSONTree:
    def __init__(self, **lookup_map_dict):
        self.properties: _Properties = _Properties(**lookup_map_dict["properties"])
        self.selectors: _Selectors = _Selectors(**lookup_map_dict["selectors"])
        self.request_method: Literal["http", "curl", "flare"] = lookup_map_dict["request_method"]
        self.rx: re.Pattern = re.compile(lookup_map_dict["url_regex"])
        self.search: _SearchProperties = _SearchProperties(**lookup_map_dict["search"])
        self.uses_ajax: bool = lookup_map_dict["chapter_ajax"] is not None
        self.custom_headers: _CustomHeaders = _CustomHeaders(**lookup_map_dict.get("custom_headers", {}))
