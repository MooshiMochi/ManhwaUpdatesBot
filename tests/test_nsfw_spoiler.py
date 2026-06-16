from manhwa_bot.ui.components.nsfw import normalize_mode, should_spoiler


def test_sfw_cover_never_spoilered() -> None:
    for mode in ("always", "never", "nsfw_channel_aware"):
        assert should_spoiler(False, mode=mode) is False
        assert should_spoiler(None, mode=mode) is False


def test_always_mode_spoilers_nsfw_everywhere() -> None:
    assert should_spoiler(True, mode="always", channel_is_nsfw=False) is True
    assert should_spoiler(True, mode="always", channel_is_nsfw=True) is True


def test_never_mode() -> None:
    assert should_spoiler(True, mode="never", channel_is_nsfw=False) is False


def test_channel_aware_mode() -> None:
    # spoiler outside NSFW channels, reveal inside them
    assert should_spoiler(True, mode="nsfw_channel_aware", channel_is_nsfw=False) is True
    assert should_spoiler(True, mode="nsfw_channel_aware", channel_is_nsfw=True) is False


def test_default_and_unknown_mode_falls_back_to_always() -> None:
    assert should_spoiler(True) is True
    assert should_spoiler(True, mode="bogus") is True
    assert normalize_mode("BOGUS") == "always"
    assert normalize_mode(None) == "always"
    assert normalize_mode("Never") == "never"
