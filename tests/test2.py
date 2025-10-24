import asyncio

from curl_cffi import AsyncSession
from faker import Faker


async def write_to_file(url: str):
    # url = "https://hivetoons.org/series/true-education"

    headers = {
        "rsc": "1",
        "User-Agent": Faker().user_agent()
    }

    session = AsyncSession()

    r = await session.get(url, headers=headers)

    with open("qiscans.txt", "w", encoding="utf-8") as f:
        f.write(r.text)

    await session.close()


def read_from_file():
    with open("qiscans.txt", "r", encoding="utf-8") as f:
        text = f.read()

    import re
    from bs4 import BeautifulSoup

    pattern = re.compile('"postTitle\\":\\"(.*?)\\"')

    raw_synopsis = pattern.search(text).group(1)
    # repaired_raw_synopsis = repair_mojibake(raw_synopsis)
    html_escaped = BeautifulSoup(raw_synopsis, "html.parser").get_text(separator=' ', strip=True)

    print(html_escaped)


if __name__ == '__main__':
    asyncio.run(write_to_file(url="https://vortexscans.org/"))
    # read_from_file()
