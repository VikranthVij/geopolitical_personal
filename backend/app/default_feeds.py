"""Small discovery set; users should review source terms before enabling feeds."""
FEEDS = [
    ("UN Geneva Press Releases", "https://www.ungeneva.org/en/news-media/press-releases-list/rss.xml", 1, "GLOBAL"),
    ("International Atomic Energy Agency", "https://www.iaea.org/feeds/topnews", 1, "GLOBAL"),
    ("Firstpost World", "https://www.firstpost.com/commonfeeds/v1/mfp/rss/world.xml", 2, "GLOBAL"),
    # Google News is an aggregator; Reuters attribution in its entries is retained as such.
    ("Reuters via Google News RSS", "https://news.google.com/rss/search?q=site%3Areuters.com%2Fworld&hl=en-IN&gl=IN&ceid=IN%3Aen", 2, "GLOBAL"),
]

# Attempted during Feature 6 endpoint verification. These remain disabled because
# the public endpoints returned 403/429/404 or only stale records.
UNAVAILABLE_SOURCES = {
    "WION": "https://www.wionews.com/rss/world.xml returned HTTP 403; /rss.xml redirected to /tags/rss.xml (404).",
    "Reddit r/worldnews": "https://www.reddit.com/r/worldnews/.rss returned HTTP 403.",
    "Reddit r/geopolitics": "https://www.reddit.com/r/geopolitics/.rss returned HTTP 429; old.reddit redirected to login.",
    "Republic World": "https://www.republicworld.com/rss/world-news.xml returned HTTP 200 but latest item was 2026-08-19; West Asia feed latest item was 2024-10-04. Disabled as stale.",
    "Firstpost Vantage with Palki Sharma": "Google News filtered endpoint returned HTTP 200 but latest item was 2026-03-12; not enabled due stale results.",
}

UNAVAILABLE_FEEDS = [
    ("WION", "https://www.wionews.com/rss/world.xml", 2, "GLOBAL", "PUBLISHER", UNAVAILABLE_SOURCES["WION"]),
    ("Reddit r/worldnews", "https://www.reddit.com/r/worldnews/.rss", 4, "GLOBAL", "COMMUNITY", UNAVAILABLE_SOURCES["Reddit r/worldnews"]),
    ("Reddit r/geopolitics", "https://www.reddit.com/r/geopolitics/.rss", 4, "GLOBAL", "COMMUNITY", UNAVAILABLE_SOURCES["Reddit r/geopolitics"]),
    ("Republic World", "https://www.republicworld.com/rss/world-news.xml", 2, "GLOBAL", "PUBLISHER", UNAVAILABLE_SOURCES["Republic World"]),
    ("Firstpost Vantage via Google News", "https://news.google.com/rss/search?q=site%3Afirstpost.com%2Fvantage+Palki+Sharma&hl=en-IN&gl=IN&ceid=IN%3Aen", 2, "GLOBAL", "AGGREGATOR", UNAVAILABLE_SOURCES["Firstpost Vantage with Palki Sharma"]),
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
