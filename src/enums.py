from enum import Enum


class BookmarkSortType(Enum):
    """Bookmark sort type."""
    LAST_UPDATED_TIMESTAMP = "last_updated"
    ALPHABETICAL = "a-z"


class BookmarkViewType(Enum):
    """Bookmark view type."""
    VISUAL = "visual"
    TEXT = "text"
