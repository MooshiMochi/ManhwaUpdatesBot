import re


class Emotes:
    warning = "⚠️"
    success = "✅"
    error = "❌"


class Constants:
    no_img_available_url = "https://st4.depositphotos.com/14953852/22772/v/600/depositphotos_227725020-stock" \
                           "-illustration-image-available-icon-flat-vector.jpg"

    completed_status_set: set[str] = {
        "completed", "complete", "cancel", "cancelled", "canceled", "finish", "finished", "dropped", "drop", "end",
        "ended"
    }

    @staticmethod
    def default_headers() -> dict:
        """
        Must set the following headers:
            :Authority
            :Path
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

    google_translate_langs = [
        {"language": "Afrikaans", "code": "af"},
        {"language": "Albanian", "code": "sq"},
        {"language": "Amharic", "code": "am"},
        {"language": "Arabic", "code": "ar"},
        {"language": "Armenian", "code": "hy"},
        {"language": "Azerbaijani", "code": "az"},
        {"language": "Basque", "code": "eu"},
        {"language": "Belarusian", "code": "be"},
        {"language": "Bengali", "code": "bn"},
        {"language": "Bosnian", "code": "bs"},
        {"language": "Bulgarian", "code": "bg"},
        {"language": "Catalan", "code": "ca"},
        {"language": "Cebuano", "code": "ceb"},
        {"language": "Chinese (Simplified)", "code": "zh-CN"},
        {"language": "Chinese (Traditional)", "code": "zh-TW"},
        {"language": "Corsican", "code": "co"},
        {"language": "Croatian", "code": "hr"},
        {"language": "Czech", "code": "cs"},
        {"language": "Danish", "code": "da"},
        {"language": "Dutch", "code": "nl"},
        {"language": "English", "code": "en"},
        {"language": "Esperanto", "code": "eo"},
        {"language": "Estonian", "code": "et"},
        {"language": "Finnish", "code": "fi"},
        {"language": "French", "code": "fr"},
        {"language": "Frisian", "code": "fy"},
        {"language": "Galician", "code": "gl"},  # noqa
        {"language": "Georgian", "code": "ka"},
        {"language": "German", "code": "de"},
        {"language": "Greek", "code": "el"},
        {"language": "Gujarati", "code": "gu"},
        {"language": "Haitian Creole", "code": "ht"},
        {"language": "Hausa", "code": "ha"},
        {"language": "Hawaiian", "code": "haw"},
        {"language": "Hebrew", "code": "iw"},
        {"language": "Hindi", "code": "hi"},
        {"language": "Hmong", "code": "hmn"},
        {"language": "Hungarian", "code": "hu"},
        {"language": "Icelandic", "code": "is"},
        {"language": "Igbo", "code": "ig"},  # noqa
        {"language": "Indonesian", "code": "id"},
        {"language": "Irish", "code": "ga"},
        {"language": "Italian", "code": "it"},
        {"language": "Japanese", "code": "ja"},
        {"language": "Javanese", "code": "jw"},
        {"language": "Kannada", "code": "kn"},
        {"language": "Kazakh", "code": "kk"},
        {"language": "Khmer", "code": "km"},
        {"language": "Korean", "code": "ko"},
        {"language": "Kurdish", "code": "ku"},
        {"language": "Kyrgyz", "code": "ky"},  # noqa
        {"language": "Lao", "code": "lo"},
        {"language": "Latin", "code": "la"},
        {"language": "Latvian", "code": "lv"},
        {"language": "Lithuanian", "code": "lt"},
        {"language": "Luxembourgish", "code": "lb"},  # noqa
        {"language": "Macedonian", "code": "mk"},
        {"language": "Malagasy", "code": "mg"},
        {"language": "Malay", "code": "ms"},
        {"language": "Malayalam", "code": "ml"},
        {"language": "Maltese", "code": "mt"},
        {"language": "Maori", "code": "mi"},
        {"language": "Marathi", "code": "mr"},
        {"language": "Mongolian", "code": "mn"},
        {"language": "Myanmar (Burmese)", "code": "my"},
        {"language": "Nepali", "code": "ne"},
        {"language": "Norwegian", "code": "no"},
        {"language": "Nyanja (Chichewa)", "code": "ny"},  # noqa
        {"language": "Pashto", "code": "ps"},
        {"language": "Persian", "code": "fa"},
        {"language": "Polish", "code": "pl"},
        {"language": "Portuguese (Portugal, Brazil)", "code": "pt"},
        {"language": "Punjabi", "code": "pa"},
        {"language": "Romanian", "code": "ro"},
        {"language": "Russian", "code": "ru"},
        {"language": "Samoan", "code": "sm"},
        {"language": "Scots Gaelic", "code": "gd"},
        {"language": "Serbian", "code": "sr"},
        {"language": "Sesotho", "code": "st"},
        {"language": "Shona", "code": "sn"},
        {"language": "Sindhi", "code": "sd"},
        {"language": "Sinhala (Sinhalese)", "code": "si"},  # noqa
        {"language": "Slovak", "code": "sk"},
        {"language": "Slovenian", "code": "sl"},
        {"language": "Somali", "code": "so"},
        {"language": "Spanish", "code": "es"},
        {"language": "Sundanese", "code": "su"},
        {"language": "Swahili", "code": "sw"},
        {"language": "Swedish", "code": "sv"},
        {"language": "Tagalog (Filipino)", "code": "tl"},
        {"language": "Tajik", "code": "tg"},  # noqa
        {"language": "Tamil", "code": "ta"},
        {"language": "Telugu", "code": "te"},
        {"language": "Thai", "code": "th"},
        {"language": "Turkish", "code": "tr"},
        {"language": "Ukrainian", "code": "uk"},
        {"language": "Urdu", "code": "ur"},
        {"language": "Uzbek", "code": "uz"},
        {"language": "Vietnamese", "code": "vi"},
        {"language": "Welsh", "code": "cy"},
        {"language": "Xhosa", "code": "xh"},
        {"language": "Yiddish", "code": "yi"},
        {"language": "Yoruba", "code": "yo"},
        {"language": "Zulu", "code": "zu"}]  # noqa


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
    url_img_size = re.compile(r"-?(?P<width>\d)+x(?P<height>\d)+")
    url_id = re.compile(r"/(?P<id>\d+)-")
    float_num = re.compile(r"(?P<float_num>[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+))")
    mangadex_url = re.compile(
        r"(?:https?://)?(?:www\.)?mangadex\.org/title/(?P<id>[a-zA-Z0-9-]+)(?:/.*)?"
    )

    comick_url = re.compile(
        r"(?:https?://)?(?:www\.)?comick\.app/comic/(?P<url_name>[a-zA-Z0-9-]+)(?:\??/.*)?"
    )
