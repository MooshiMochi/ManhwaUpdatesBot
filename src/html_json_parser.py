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
