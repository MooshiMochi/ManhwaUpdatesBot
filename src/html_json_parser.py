import json
import re

from bs4 import BeautifulSoup, Tag


class Parser:
    """
        A class that provides utility functions to parse JSON-like strings from HTML.
        The main purpose is to extract JSON-like strings from <script> tags in HTML.
        Example usage:
        >>> text = '<script>var data = { "key": "value" }</script>'
        >>> parser = Parser.parse_text(text)
        >>> print(parser)
        {'key': 'value'}
        """

    @staticmethod
    def _get_longest_tag(text: str) -> Tag:
        """
        Given a string of HTML, returns the longest <script> tag.
        """
        soup = BeautifulSoup(text, 'html.parser')
        tags = soup.find_all('script')
        longest_tag = max(tags, key=lambda x: len(x.text))
        return longest_tag

    @staticmethod
    def _extract_json_string(string: str) -> str:
        """
        Extracts a JSON-like substring from a string.
        The substring must contain at least 3 characters and be enclosed in curly braces.
        Returns the longest match found.
        """
        # pattern = r'((\[[^\}]{3,})?\{s*[^\}\{]{3,}?:.*\}([^\{]+\])?)'  # Source: https://stackoverflow.com/a/73680455/15874349
        pattern = r'(\{.*\}|\[.*\])'  # Source: https://chatgpt.com - Model 03-mini
        return max(re.search(pattern, string).groups(), key=lambda x: len(x) if x is not None else -1)

    @classmethod
    def _extract_and_parse_json(cls, text: str) -> dict | list | str:
        """
        Extracts a JSON-like substring from the provided text and attempts to convert it
        using json.loads. The resulting object is then traversed recursively:
          - Every string value is processed again in an attempt to convert nested JSON.
          - If conversion fails at any point, the value is left as a string.
        """
        try:
            candidate = cls._extract_json_string(text)
        except Exception as e:  # noqa: If extraction fails, return the original text.
            return text

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:  # If JSON parsing fails, return the original text.
            return text

        def recursive_convert(obj):
            if isinstance(obj, dict):
                return {key: recursive_convert(value) for key, value in obj.items()}  # noqa: Scope Warning
            elif isinstance(obj, list):
                return [recursive_convert(item) for item in obj]
            elif isinstance(obj, str):
                # Recursively try to extract and parse any nested JSON.
                return cls._extract_and_parse_json(obj)
            else:
                return obj

        return recursive_convert(data)

    @classmethod
    def parse_text(cls, text: str) -> dict | list | str:
        """
        Processes the provided HTML text (or self.html if none is provided) to extract and parse
        JSON from the longest <script> tag.
        """
        tag = cls._get_longest_tag(text)
        json_objects = cls._extract_and_parse_json(tag.text)
        return json_objects

    @classmethod
    def extract_balanced_json_v2(cls, text, start_key='"post":{'):
        start = text.find(start_key)
        if start == -1:
            raise ValueError("Couldn't find the post object start")
        i = start + len(start_key) - 1  # position on the opening '{
        json_data = cls._extract_json_string(text[i:])
        return json_data

    @staticmethod
    def extract_balanced_json(text, start_key='"post":{'):
        """Return the JSON text for the object that starts right after start_key."""
        start = text.find(start_key)
        if start == -1:
            raise ValueError("Couldn't find the post object start")
        i = start + len(start_key) - 1  # position on the opening '{'
        depth = 0
        arr_depth = 0
        in_str = False
        esc = False
        _debug_so_far = ""
        for j in range(i, len(text)):
            ch = text[j]
            _debug_so_far += ch
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '[':
                    arr_depth += 1
                elif ch == ']':
                    arr_depth -= 1
                elif ch == '}':
                    depth -= 1

                if depth == 0 and arr_depth == 0:
                    # slice includes the outer braces
                    return text[i:j + 1]
        print("{}\ndepth: {}, arr_depth: {}".format(_debug_so_far, depth, arr_depth))
        raise ValueError("Unbalanced braces while extracting JSON")

    @staticmethod
    def repair_mojibake(s: str) -> str:
        """
        Try to reverse the classic 'UTF-8 decoded as cp1252' mojibake:
          e.g., 'donâ€™t' -> "don’t", 'â€œHelloâ€�' -> “Hello”
        Only runs when telltale patterns exist, otherwise returns s unchanged.
        """
        if not isinstance(s, str) or not s:
            return s

        # Fast bail-out if nothing suggests mojibake
        if not re.search(r'[ÂÃâ][\u0080-\u00BF]', s) and 'â' not in s and 'Â' not in s and 'Ã' not in s:
            return s

        # 1) Try the canonical reversal path: cp1252 -> utf-8
        try:
            return s.encode('cp1252', errors='strict').decode('utf-8', errors='strict')
        except (UnicodeEncodeError, UnicodeDecodeError):
            # 2) Best-effort: allow lossy encode on the cp1252 path
            try:
                fixed = s.encode('cp1252', errors='replace').decode('utf-8', errors='replace')
                return fixed
            except Exception:
                pass

        # 3) Last resort: targeted replacements for the most common triples
        replacements = {
            'â€™': '’', 'â€˜': '‘',
            'â€œ': '“', 'â€�': '”',
            'â€“': '–', 'â€”': '—',
            'â€¦': '…',
            'Â ': ' ', 'Â': '',  # stray non-breaking-space artifacts
        }
        fixed = s
        for bad, good in replacements.items():
            fixed = fixed.replace(bad, good)
        return fixed
