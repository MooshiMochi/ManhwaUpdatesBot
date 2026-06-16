from manhwa_bot.ui.components.bookmark import resolve_last_read_nav


def test_no_chapters_disables_everything() -> None:
    assert resolve_last_read_nav(None, 0) == (None, False, False)
    assert resolve_last_read_nav(3, 0) == (None, False, False)


def test_nothing_read_can_only_go_forward() -> None:
    assert resolve_last_read_nav(None, 5) == (None, False, True)


def test_first_chapter_back_disabled_forward_enabled() -> None:
    assert resolve_last_read_nav(0, 5) == (0, False, True)


def test_latest_chapter_forward_disabled_back_enabled() -> None:
    assert resolve_last_read_nav(4, 5) == (4, True, False)


def test_middle_chapter_both_enabled() -> None:
    assert resolve_last_read_nav(2, 5) == (2, True, True)


def test_stale_index_above_range_clamps_to_latest() -> None:
    # Carried-over index larger than the current chapter list: must clamp to the
    # last real chapter (back enabled, forward disabled) instead of inverting the
    # states / indexing out of bounds.
    assert resolve_last_read_nav(50, 5) == (4, True, False)


def test_negative_index_clamps_to_first() -> None:
    assert resolve_last_read_nav(-3, 5) == (0, False, True)


def test_single_chapter_both_disabled() -> None:
    assert resolve_last_read_nav(0, 1) == (0, False, False)
