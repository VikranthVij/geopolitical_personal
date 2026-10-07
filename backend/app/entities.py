"""Small, deterministic geopolitical alias extractor; it does not infer event roles."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    name: str
    kind: str
    aliases: tuple[str, ...]
    country_code: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Mention:
    surface: str
    start: int
    end: int
    entity_name: str | None
    entity_type: str
    confidence: str
    field: str


SPECS = [
    EntitySpec("Donald Trump", "PERSON", ("Donald Trump", "President Trump"), "US"),
    EntitySpec("Benjamin Netanyahu", "PERSON", ("Benjamin Netanyahu", "Netanyahu"), "IL"),
    EntitySpec("Narendra Modi", "PERSON", ("Narendra Modi", "Prime Minister Modi"), "IN"),
    EntitySpec("Iran", "COUNTRY", ("Iran", "Islamic Republic of Iran"), "IR"),
    EntitySpec("Israel", "COUNTRY", ("Israel", "Israeli"), "IL"),
    EntitySpec("United States", "COUNTRY", ("United States of America", "United States", "USA", "U.S.A.", "U.S.", "U.S", "US"), "US"),
    EntitySpec("India", "COUNTRY", ("India", "Indian"), "IN"),
    EntitySpec("Russia", "COUNTRY", ("Russia", "Russian Federation", "Russian"), "RU"),
    EntitySpec("China", "COUNTRY", ("China", "Chinese"), "CN"),
    EntitySpec("Ukraine", "COUNTRY", ("Ukraine", "Ukrainian"), "UA"),
    EntitySpec("Taiwan", "COUNTRY", ("Taiwan",), "TW"),
    EntitySpec("Islamic Revolutionary Guard Corps", "ORGANIZATION", ("Islamic Revolutionary Guard Corps", "Iranian Revolutionary Guard", "IRGC"), "IR"),
    EntitySpec("Government of Iran", "ORGANIZATION", ("Iranian government", "Government of Iran", "Tehran government"), "IR"),
    EntitySpec("United States Department of Defense", "ORGANIZATION", ("Department of Defense", "U.S. Department of Defense", "US Department of Defense", "Pentagon"), "US"),
    EntitySpec("North Atlantic Treaty Organization", "ORGANIZATION", ("North Atlantic Treaty Organization", "NATO")),
    EntitySpec("International Atomic Energy Agency", "ORGANIZATION", ("International Atomic Energy Agency", "IAEA")),
    EntitySpec("United Nations", "ORGANIZATION", ("United Nations", "UN")),
    EntitySpec("Indian Navy", "ORGANIZATION", ("Indian Navy",)),
    EntitySpec("Quds Force", "MILITARY_UNIT", ("Quds Force", "IRGC Quds Force"), "IR"),
    EntitySpec("Ballistic missile", "WEAPON_SYSTEM", ("ballistic missiles", "ballistic missile")),
    EntitySpec("Shahed-136", "WEAPON_SYSTEM", ("Shahed-136", "Shahed 136", "Shahed‑136"), "IR"),
    EntitySpec("F-35", "AIRCRAFT", ("F-35", "F35"), "US"),
    EntitySpec("B-2 Spirit", "AIRCRAFT", ("B-2 Spirit", "B-2", "B2 Spirit"), "US"),
    EntitySpec("Tomahawk", "WEAPON_SYSTEM", ("Tomahawk missiles", "Tomahawk"), "US"),
    EntitySpec("S-400", "WEAPON_SYSTEM", ("S-400", "S400"), "RU"),
    EntitySpec("Strait of Hormuz", "LOCATION", ("Strait of Hormuz", "Hormuz Strait")),
    EntitySpec("Taiwan Strait", "LOCATION", ("Taiwan Strait",)),
    EntitySpec("Gaza Strip", "LOCATION", ("Gaza Strip", "Gaza")),
    EntitySpec("Tehran", "LOCATION", ("Tehran",)),
    EntitySpec("Red Sea", "LOCATION", ("Red Sea",)),
    EntitySpec("Arabian Sea", "LOCATION", ("Arabian Sea",)),
    EntitySpec("Natanz nuclear facility", "INFRASTRUCTURE", ("Natanz nuclear facility", "Natanz facility", "Natanz"), "IR"),
    EntitySpec("aircraft carrier", "VESSEL", ("aircraft carrier", "aircraft carriers")),
    EntitySpec("Aircraft", "AIRCRAFT", ("aircraft",)),
    EntitySpec("OPEC", "ECONOMIC_ENTITY", ("OPEC", "Organization of the Petroleum Exporting Countries")),
    EntitySpec("Reserve Bank of India", "ECONOMIC_ENTITY", ("Reserve Bank of India", "RBI"), "IN"),
]

_ALIASES: list[tuple[EntitySpec, str, re.Pattern[str]]] = []
for _spec in SPECS:
    for _alias in set((_spec.name, *_spec.aliases)):
        # The unpunctuated "US" abbreviation is uppercase-only to avoid matching the pronoun "us".
        flags = 0 if _alias == "US" else re.IGNORECASE
        _ALIASES.append((_spec, _alias, re.compile(r"(?<!\w)" + re.escape(_alias) + r"(?!\w)", flags)))
_ALIASES.sort(key=lambda x: len(x[1]), reverse=True)


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))


def extract_mentions(title: str | None, excerpt: str | None) -> list[Mention]:
    result: list[Mention] = []
    for field, text in (("TITLE", title or ""), ("EXCERPT", excerpt or "")):
        occupied: list[tuple[int, int]] = []
        candidates = []
        for spec, alias, pattern in _ALIASES:
            # Ignore noisy one-letter aliases such as UN except in their uppercase spelling.
            for match in pattern.finditer(text):
                surface = match.group()
                if alias == "US" and surface != "US":
                    continue
                candidates.append((match.start(), match.end(), spec, surface))
        # Longest spelling wins on overlaps; every distinct occurrence remains a mention.
        candidates.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        for start, end, spec, surface in candidates:
            if any(start < old_end and end > old_start for old_start, old_end in occupied):
                continue
            occupied.append((start, end))
            result.append(Mention(surface, start, end, spec.name, spec.kind, "HIGH", field))
        # Unknown organization-like phrases are retained without inventing a canonical identity.
        for match in re.finditer(r"\b(?:Iranian|Israeli|Russian|Chinese|Ukrainian|regional)\s+(?:forces|military|troops)\b", text, re.I):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            surface = match.group()
            result.append(Mention(surface, match.start(), match.end(), None, "ORGANIZATION", "UNRESOLVED", field))
        for match in re.finditer(r"\bWashington\b", text, re.I):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            result.append(Mention(match.group(), match.start(), match.end(), None, "LOCATION", "UNRESOLVED", field))
    return sorted(result, key=lambda m: (m.field, m.start, m.end))


async def persist_document_mentions(conn, document_id, title: str, excerpt: str | None) -> None:
    """Upsert canonical entities and replace this document's mentions atomically."""
    mentions = extract_mentions(title, excerpt)
    by_name = {m.entity_name for m in mentions if m.entity_name}
    ids = {}
    specs = {s.name: s for s in SPECS}
    for name in by_name:
        spec = specs[name]
        row = await (await conn.execute(
            "INSERT INTO entities(canonical_name,type,country_code,description) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(canonical_name,type) DO UPDATE SET updated_at=now() RETURNING id",
            (spec.name, spec.kind, spec.country_code, spec.description),
        )).fetchone()
        ids[name] = row["id"]
        for alias in set((spec.name, *spec.aliases)):
            await conn.execute(
                "INSERT INTO entity_aliases(entity_id,alias,normalized_alias) VALUES(%s,%s,%s) ON CONFLICT(entity_id,normalized_alias) DO NOTHING",
                (row["id"], alias, normalize_name(alias)),
            )
    await conn.execute("DELETE FROM document_entity_mentions WHERE document_id=%s", (document_id,))
    for m in mentions:
        await conn.execute(
            "INSERT INTO document_entity_mentions(document_id,entity_id,surface_text,normalized_text,text_field,character_start,character_end,entity_type,extraction_method,resolution_confidence) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'DETERMINISTIC_ALIAS',%s)",
            (document_id, ids.get(m.entity_name), m.surface, normalize_name(m.surface), m.field, m.start, m.end, m.entity_type, m.confidence),
        )
