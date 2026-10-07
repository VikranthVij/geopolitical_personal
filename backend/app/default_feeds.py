"""Small discovery set; users should review source terms before enabling feeds."""
FEEDS = [
    ("UN Geneva Press Releases", "https://www.ungeneva.org/en/news-media/press-releases-list/rss.xml", 1, "GLOBAL"),
    ("International Atomic Energy Agency", "https://www.iaea.org/feeds/topnews", 1, "GLOBAL"),
]

RETIRED_FEED_NAMES = ("United Nations News", "India Ministry of External Affairs", "NATO News")

# The IAEA feed also carries science and health news. Retain only headlines with
# clear country, security, safeguards, conflict, or strategic-energy context.
IAEA_RELEVANCE_TERMS = (
    "ukraine", "russia", "iran", "korea", "safeguard", "nuclear safety",
    "nuclear power", "nuclear energy", "nuclear plant", "nuclear facility",
    "director general statement", "non-proliferation", "proliferation", "npt",
    "conflict", "war", "attack", "radiological", "atomic energy",
)


def is_relevant_iaea(text: str) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in IAEA_RELEVANCE_TERMS)
