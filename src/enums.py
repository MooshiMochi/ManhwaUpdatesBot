from enum import Enum


class BookmarkSortType(Enum):
    """Bookmark sort type."""
    LAST_UPDATED_TIMESTAMP = "last_updated"
    ALPHABETICAL = "a-z"


class BookmarkViewType(Enum):
    """Bookmark view type."""
    VISUAL = "visual"
    TEXT = "text"


class Minutes(Enum):
    """The representation of minutes in seconds."""
    ONE = 60
    TWO = 120
    THREE = 180
    FIVE = 300
    TEN = 600
    FIFTEEN = 900
    TWENTY = 1200
    THIRTY = 1800
    FORTY = 2400
    FIFTY = 3000
    SIXTY = 3600


class Hours(Enum):
    """The representation of hours in seconds"""
    ONE = Minutes.SIXTY.value
    TWO = Minutes.SIXTY.value * 2
    THREE = Minutes.SIXTY.value * 3
    TEN = Minutes.SIXTY.value * 10
    TWELVE = Minutes.SIXTY.value * 12
    FIFTEEN = Minutes.SIXTY.value * 15
    TWENTY = Minutes.SIXTY.value * 20
    TWENTY_FOUR = Minutes.SIXTY.value * 24


class BookmarkFolderType(Enum):
    """Bookmark folder type."""
    Reading = "reading"
    Planned = "planned"
    Finished = "finished"
    Dropped = "dropped"
    Subscribed = "subscribed"
    All = "all"
