"""Thin async client for Google's free (unofficial) Translate endpoint.

Uses the same ``translate.googleapis.com/translate_a/single`` endpoint that
v1 relied on, so no API key is required.
"""

from __future__ import annotations

import urllib.parse

import aiohttp

_ENDPOINT = "https://translate.googleapis.com/translate_a/single"

# ISO 639-1 code → display name. Hard-coded so autocomplete needs no API call.
_LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",
    "sq": "Albanian",
    "am": "Amharic",
    "ar": "Arabic",
    "hy": "Armenian",
    "az": "Azerbaijani",
    "eu": "Basque",
    "be": "Belarusian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "ceb": "Cebuano",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "co": "Corsican",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "eo": "Esperanto",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Frisian",
    "gl": "Galician",
    "ka": "Georgian",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "ht": "Haitian Creole",
    "ha": "Hausa",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "hi": "Hindi",
    "hmn": "Hmong",
    "hu": "Hungarian",
    "is": "Icelandic",
    "ig": "Igbo",
    "id": "Indonesian",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "jv": "Javanese",
    "kn": "Kannada",
    "kk": "Kazakh",
    "km": "Khmer",
    "rw": "Kinyarwanda",
    "ko": "Korean",
    "ku": "Kurdish",
    "ky": "Kyrgyz",
    "lo": "Lao",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "lb": "Luxembourgish",
    "mk": "Macedonian",
    "mg": "Malagasy",
    "ms": "Malay",
    "ml": "Malayalam",
    "mt": "Maltese",
    "mi": "Maori",
    "mr": "Marathi",
    "mn": "Mongolian",
    "my": "Myanmar (Burmese)",
    "ne": "Nepali",
    "no": "Norwegian",
    "ny": "Nyanja (Chichewa)",
    "or": "Odia (Oriya)",
    "ps": "Pashto",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ro": "Romanian",
    "ru": "Russian",
    "sm": "Samoan",
    "gd": "Scots Gaelic",
    "sr": "Serbian",
    "st": "Sesotho",
    "sn": "Shona",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "es": "Spanish",
    "su": "Sundanese",
    "sw": "Swahili",
    "sv": "Swedish",
    "tl": "Tagalog (Filipino)",
    "tg": "Tajik",
    "ta": "Tamil",
    "tt": "Tatar",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "tk": "Turkmen",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "ug": "Uyghur",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "cy": "Welsh",
    "xh": "Xhosa",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zu": "Zulu",
}


class TranslateError(Exception):
    """Raised when a translation request fails."""


def language_choices(current: str) -> list[tuple[str, str]]:
    """Return ``(code, display_name)`` pairs matching *current* (up to 25).

    Matches against both the ISO code and the display name, case-insensitively.
    """
    low = current.lower()
    results: list[tuple[str, str]] = []
    for code, name in _LANGUAGES.items():
        if low in code.lower() or low in name.lower():
            results.append((code, name))
        if len(results) == 25:
            break
    return results


async def translate(
    text: str,
    *,
    target: str = "en",
    source: str = "auto",
    session: aiohttp.ClientSession,
) -> tuple[str, str]:
    """Translate *text* and return ``(translated_text, detected_source_language)``.

    Raises :class:`TranslateError` on HTTP errors or unexpected response shapes.
    """
    params = {
        "client": "gtx",
        "sl": source,
        "tl": target,
        "dt": "t",
        "q": text,
    }
    url = f"{_ENDPOINT}?{urllib.parse.urlencode(params)}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise TranslateError(f"HTTP {resp.status} from translate API")
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as exc:
        raise TranslateError(f"Network error: {exc}") from exc

    try:
        chunks: list[str] = [pair[0] for pair in data[0] if pair[0]]
        translated = "".join(chunks)
        detected: str = data[2] if len(data) > 2 and isinstance(data[2], str) else source
    except (IndexError, TypeError, KeyError) as exc:
        raise TranslateError(f"Unexpected response format: {exc}") from exc

    if not translated:
        raise TranslateError("Translation returned empty result")

    return translated, detected
