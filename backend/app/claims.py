"""Bounded, deterministic claim candidates. This records source assertions, not truth."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from .entities import extract_mentions

CLAIM_TYPES = {"OCCURRENCE", "ATTRIBUTION", "LOCATION", "TIME", "QUANTITATIVE", "INTENT", "STATUS", "RESPONSE", "CONSEQUENCE"}
POLARITIES = {"AFFIRMED", "NEGATED"}
EPISTEMIC = {"ASSERTED", "REPORTED", "ALLEGED", "POSSIBLE", "UNCERTAIN", "DENIED"}
ATTRIBUTION_TYPES = {"DIRECT_SOURCE_ASSERTION", "ATTRIBUTED_ASSERTION", "REPORTED_ASSERTION"}
QUANTITY_OPERATORS = {"EQ", "GT", "GTE", "LT", "LTE", "APPROX", "RANGE", "UNKNOWN"}


@dataclass(frozen=True)
class SourceSpan:
    text_field: str
    character_start: int
    character_end: int
    source_text: str


@dataclass(frozen=True)
class ClaimCandidate:
    type: str
    statement: str
    spans: tuple[SourceSpan, ...]
    normalized: dict = field(default_factory=dict)
    polarity: str = "AFFIRMED"
    status: str = "ASSERTED"
    epistemic_status: str = "ASSERTED"
    attribution_type: str = "DIRECT_SOURCE_ASSERTION"
    attribution: dict = field(default_factory=dict)
    intent_label: str = "UNKNOWN"
    extraction_confidence: str = "MEDIUM"

    @property
    def identity(self) -> str:
        body = {"type": self.type, "normalized": self.normalized, "polarity": self.polarity,
                "epistemic_status": self.epistemic_status, "intent_label": self.intent_label,
                "attribution_type": self.attribution_type, "attribution": self.attribution}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ClaimExtractor(Protocol):
    def extract(self, title: str | None, excerpt: str | None, published_at=None) -> list[ClaimCandidate]: ...


class DeterministicClaimExtractor:
    """Replaceable local implementation; deliberately makes no truth judgments."""

    def extract(self, title: str | None, excerpt: str | None, published_at=None) -> list[ClaimCandidate]:
        return extract_document_claims(title, excerpt, published_at)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_QUANTITY = re.compile(
    r"(?:(?P<range>between\s+(?P<lo>\d[\d,]*)\s+and\s+(?P<hi>\d[\d,]*))|"
    r"(?P<qual>dozens|hundreds|thousands|scores)\s+of|"
    r"(?P<op>more than|over|at least|no fewer than|fewer than|less than|under|approximately|about|around|roughly|nearly|exactly)?\s*"
    r"(?P<value>\d[\d,]*)(?:\s*(?:-|to)\s*(?P<hi2>\d[\d,]*))?)\s*"
    r"(?P<unit>missiles?|rockets?|drones?|aircraft|people|troops|soldiers|ships?|vessels?|casualties|deaths|injuries|facilities|sites|percent|%)?",
    re.I,
)
_TEMPORAL = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:\s+morning|\s+afternoon|\s+evening|\s+night)?\b|"
    r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?:\s*UTC)?)?\b|"
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,\s*\d{4})?\b|"
    r"\b\d{1,2}:\d{2}\s*UTC\b|\b(?:earlier this week|later that day|the previous day|overnight|today|yesterday|last night)\b",
    re.I,
)
_ACTIONS = {
    "launch": r"\b(?:launch(?:ed|es|ing)?|fire(?:d|s|ing)?|fired|fire)\b",
    "strike": r"\b(?:struck|strikes|striking|attacked|attacking)\b",
    "deploy": r"\bdeploy(?:ed|s|ing)?\b",
    "damage": r"\b(?:damage(?:d|s|ing)?|destroy(?:ed|s|ing)?)\b",
    "kill": r"\b(?:kill(?:ed|s|ing)?|slain)\b",
    "injure": r"\b(?:injur(?:ed|es|ing)|wound(?:ed|s|ing)?)\b",
    "intercept": r"\bintercept(?:ed|s|ing)?\b",
    "withdraw": r"\bwithdraw(?:s|d|ing)?\b",
    "explode": r"\b(?:explode(?:d|s|ing)?|detonat(?:ed|es|ing))\b",
    "respond": r"\b(?:respond(?:ed|s|ing)?|retaliat(?:ed|es|ing))\b",
}


def _sentences(text: str):
    # Preserve original character offsets; avoid splitting common initialisms.
    protected = re.sub(r"\b(?:U\.S|U\.N|U\.K|e\.g|i\.e)\.", lambda m: m.group().replace(".", "\u2024"), text or "", flags=re.I)
    start = 0
    for match in _SENTENCE_SPLIT.finditer(protected):
        yield start, match.start(), text[start:match.start()].strip()
        start = match.end()
    if start < len(text or ""):
        yield start, len(text), (text or "")[start:].strip()


def _locate_trimmed(text: str, approximate_start: int, sentence: str) -> tuple[int, int]:
    start = approximate_start
    while start < len(text) and text[start].isspace():
        start += 1
    return start, start + len(sentence)


def _entity_roles(sentence: str, action_start: int) -> dict:
    mentions = extract_mentions(sentence, "")
    named = [m for m in mentions if m.entity_name]
    before = [m for m in named if m.end <= action_start]
    after = [m for m in named if m.start >= action_start]
    roles: dict[str, str] = {}
    actors = [m for m in before if m.entity_type in {"PERSON", "ORGANIZATION", "COUNTRY", "MILITARY_UNIT"}]
    passive = bool(re.search(r"\b(?:was|were|is|are|been|being)\s+(?:launch(?:ed)?|fired|struck|attacked|deployed|destroyed|damaged|killed|injured|intercepted)\b", sentence, re.I))
    if actors and not passive:
        roles["actor"] = actors[-1].entity_name
    object_types = {"WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "INFRASTRUCTURE"}
    objects = [m for m in (*before, *after) if m.entity_type in object_types and (m.start >= action_start or passive)]
    if objects:
        roles["object"] = objects[0].entity_name
    if passive:
        agent = re.search(r"\bby\s+", sentence[action_start:], re.I)
        if agent:
            agent_start = action_start + agent.end()
            by_entities = [m for m in after if m.start >= agent_start and m.entity_type in {"PERSON", "ORGANIZATION", "COUNTRY", "MILITARY_UNIT"}]
            if by_entities:
                roles["actor"] = by_entities[0].entity_name
    target_prep = re.search(r"\b(?:toward|towards|against|at|on|into)\s+", sentence[action_start:], re.I)
    if target_prep:
        target_start = action_start + target_prep.end()
        targets = [m for m in after if m.start >= target_start]
        if targets:
            roles["target"] = targets[0].entity_name
    # Keep unresolved surface participants without assigning them canonical identities.
    if not actors and not passive:
        loose = re.search(r"\b([A-Z][\w-]+(?:\s+[A-Z][\w-]+)*)\s+(?:launched|fired|struck|attacked|deployed)\b", sentence)
        if loose:
            roles["actor_text"] = loose.group(1)
    return roles


def _location_hint(sentence: str):
    match = re.search(r"\b(?:in|at|from|near|within)\s+(?!(?:least|most|about|approximately|around|roughly)\b)(?:the\s+)?([A-Za-z][\w-]*(?:\s+[A-Za-z][\w-]*){0,3})", sentence, re.I)
    if not match:
        return None
    recognized = extract_mentions(match.group(1), "")
    if any(m.entity_type in {"COUNTRY", "LOCATION", "INFRASTRUCTURE"} for m in recognized):
        return match
    return None


def _is_negated(sentence: str, predicate_start: int) -> bool:
    prefix = sentence[:predicate_start]
    boundaries = [prefix.rfind(token) for token in (";", ",", " and ", " but ", " while ", " whereas ")]
    prefix = prefix[max(boundaries, default=-1) + 1:]
    return bool(re.search(
        r"\b(?:did\s+not|didn't|does\s+not|doesn't|has\s+not|hasn't|have\s+not|haven't|had\s+not|hadn't|is\s+not|isn't|was\s+not|wasn't|were\s+not|weren't|never|not)(?:\s+\w+){0,3}\s*$",
        prefix, re.I,
    ))


def _quantity(text: str) -> tuple[dict, int] | None:
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", text) and not re.search(r"\b(?:missiles?|rockets?|drones?|aircraft|people|troops|soldiers|ships?|vessels?|casualties|deaths|injuries|facilities|sites|percent|%)\b", text, re.I):
        return None
    m = _QUANTITY.search(text)
    if not m:
        return None
    original = m.group().strip()
    if m.group("range") or m.group("hi2"):
        lo = m.group("lo") or m.group("value")
        hi = m.group("hi") or m.group("hi2")
        return ({"original": original, "operator": "RANGE", "min": int(lo.replace(",", "")),
                 "max": int(hi.replace(",", "")), "unit": m.group("unit")}, m.start())
    qualitative = m.group("qual")
    if qualitative:
        return ({"original": original, "operator": "UNKNOWN", "value": None, "qualifier": qualitative.lower(), "unit": m.group("unit")}, m.start())
    if not m.group("unit") and not m.group("op"):
        return None
    op = (m.group("op") or "").lower()
    operator = {"more than": "GT", "over": "GT", "at least": "GTE", "no fewer than": "GTE",
                "fewer than": "LT", "less than": "LT", "under": "LT", "approximately": "APPROX",
                "about": "APPROX", "around": "APPROX", "roughly": "APPROX", "nearly": "APPROX",
                "exactly": "EQ", "": "EQ"}.get(op, "UNKNOWN")
    value = int(m.group("value").replace(",", ""))
    return ({"original": original, "operator": operator, "value": value, "unit": m.group("unit")}, m.start())


def _attribution(sentence: str) -> tuple[dict, str, str, str]:
    lower = sentence.lower()
    markers = [(m.start(), m.group().lower()) for m in re.finditer(r"\b(?:reported|reportedly|reports|said|claimed|alleged|accused|believe|believes|believed|according to)\b", sentence, re.I)]
    if not markers:
        return {}, "DIRECT_SOURCE_ASSERTION", "ASSERTED", "ASSERTED"
    pos, marker = markers[-1]
    speaker = sentence[:pos].strip(" ,:;\"")
    if marker == "according to":
        speaker = sentence[pos + len(marker):].split(",", 1)[0].strip(" ,:;\"")
    chain = re.search(r"\b(?:Reuters|AP|Associated Press|AFP)\s+reported\s+that\s+(.+?\b(?:officials|military|minister|spokesperson|commander)\b)\s+(?:said|claimed|alleged|accused)\b", sentence, re.I)
    if chain:
        speaker = chain.group(1)
    # Avoid storing an entire paragraph as an attributed speaker.
    speaker = " ".join(speaker.split()[-6:])[:160]
    is_reported_chain = bool(re.search(r"\b(?:Reuters|AP|Associated Press|AFP)\s+reported\b", lower, re.I))
    ep = "ALLEGED" if marker in {"claimed", "alleged", "accused"} else "REPORTED"
    if re.search(r"\b(?:may|might|could|possibly|perhaps)\b", lower):
        ep = "POSSIBLE"
    elif re.search(r"\b(?:likely|believe|believes|believed|appears to)\b", lower):
        ep = "UNCERTAIN"
    reporter_match = re.search(r"\b(Reuters|AP|Associated Press|AFP)\s+reported\b", sentence, re.I)
    reporter = reporter_match.group(1) if reporter_match else None
    reported_assertion = is_reported_chain or marker in {"reported", "reportedly"}
    return {"speaker_text": speaker if marker not in {"reported", "reportedly", "reports"} else None,
            "marker": marker, "reported_by": reporter}, ("REPORTED_ASSERTION" if reported_assertion else "ATTRIBUTED_ASSERTION"), ep, ep


def extract_document_claims(title: str | None, excerpt: str | None, published_at=None) -> list[ClaimCandidate]:
    candidates: list[ClaimCandidate] = []
    for field_name, text in (("TITLE", title or ""), ("EXCERPT", excerpt or "")):
        for base, end, sentence in _sentences(text):
            sentence = sentence.strip()
            if not sentence:
                continue
            start, stop = _locate_trimmed(text, base, sentence)
            span = SourceSpan(field_name, start, stop, text[start:stop])
            low = sentence.casefold()
            attribution, attribution_type, epistemic, status = _attribution(sentence)
            denial = re.search(r"\b(?:denied|reject(?:ed|s)|refut(?:ed|es))\b", sentence, re.I)
            no_evidence = re.search(r"\bno evidence (?:has emerged|shows|that)\b", sentence, re.I)
            if denial:
                denied_by = [m for m in extract_mentions(sentence[:denial.start()], "") if m.entity_name]
                denied_by_name = denied_by[-1].entity_name if denied_by else None
                candidates.append(ClaimCandidate("RESPONSE", sentence, (span,), {"action": "deny", "actor": denied_by_name, "denied_proposition": sentence[denial.end():].strip()}, "AFFIRMED", "DENIED", "DENIED", attribution_type, {**attribution, "speaker_text": sentence[:denial.start()].strip()}, "UNKNOWN", "HIGH"))
                continue
            if no_evidence:
                candidates.append(ClaimCandidate("STATUS", sentence, (span,), {"state": "NO_EVIDENCE_REPORTED"}, "AFFIRMED", "UNCERTAIN", "UNCERTAIN", attribution_type, attribution, "UNKNOWN", "HIGH"))
                continue

            intent_match = re.search(r"\b(?:intended to|intended as|aimed to|designed to|retaliation|retaliate|deter)\b", sentence, re.I)
            epistemic_modifier = ("POSSIBLE" if re.search(r"\b(?:may|might|could|possibly|perhaps)\b", low)
                                 else "UNCERTAIN" if re.search(r"\b(?:likely|believe|believes|believed|appears to)\b", low)
                                 else "REPORTED" if "reportedly" in low else epistemic)
            uncertainty = epistemic_modifier in {"POSSIBLE", "UNCERTAIN"}
            effective_epistemic = epistemic_modifier
            base_effective_status = "UNCERTAIN" if uncertainty else ("REPORTED" if epistemic_modifier == "REPORTED" and status == "ASSERTED" else status)
            quantity_match = _quantity(sentence)
            quantity, quantity_start = quantity_match if quantity_match else (None, None)
            temporal_values = [m.group() for m in _TEMPORAL.finditer(sentence)]
            location_hint = _location_hint(sentence)
            if intent_match:
                intent_label = "SPECULATION" if re.search(r"\b(?:may|might|could|possibly|perhaps|speculat\w*)\b", low) else ("INFERENCE" if re.search(r"\b(?:analysts?|believe|believes|likely|appears to)\b", low) else "REPORTED_INTENT")
                intent_negated = _is_negated(sentence, intent_match.start())
                candidates.append(ClaimCandidate("INTENT", sentence, (span,), {"intent_expression": intent_match.group(), "actor": None}, "NEGATED" if intent_negated else "AFFIRMED", "NEGATED" if intent_negated else base_effective_status, "POSSIBLE" if uncertainty else epistemic, attribution_type, attribution, intent_label, "MEDIUM"))

            action_hits = []
            for name, pattern in _ACTIONS.items():
                for match in re.finditer(pattern, sentence, re.I):
                    if name == "strike" and match.group().lower() == "strikes" and re.match(r"\s+(?:were|was|have|has|are|is)\b", sentence[match.end():], re.I):
                        continue
                    action_hits.append((match.start(), name, match))
            action_hits.sort(key=lambda item: item[0])
            if action_hits:
                _, action_name, action_match = action_hits[0]
                negated = _is_negated(sentence, action_match.start())
                roles = {**_entity_roles(sentence, action_match.start()), "predicate_surface": action_match.group().casefold(), "quantity": quantity, "time_expressions": temporal_values,
                         "location_text": location_hint.group(1) if location_hint else None}
                if action_name in {"damage", "kill", "injure"}:
                    claim_type = "CONSEQUENCE"
                elif action_name == "respond":
                    claim_type = "RESPONSE"
                else:
                    claim_type = "OCCURRENCE"
                action_status = "NEGATED" if negated else base_effective_status
                candidates.append(ClaimCandidate(claim_type, sentence, (span,), {"action": action_name, **roles}, "NEGATED" if negated else "AFFIRMED", action_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "HIGH" if not uncertainty else "MEDIUM"))
                if attribution_type != "DIRECT_SOURCE_ASSERTION":
                    candidates.append(ClaimCandidate("ATTRIBUTION", sentence, (span,), {"asserted_proposition": {"action": action_name, **roles}}, "AFFIRMED", effective_epistemic, effective_epistemic, attribution_type, attribution, "UNKNOWN", "HIGH"))
                for _, later_action, later_match in action_hits[1:]:
                    later_negated = _is_negated(sentence, later_match.start())
                    later_roles = {**_entity_roles(sentence, later_match.start()), "predicate_surface": later_match.group().casefold(), "quantity": quantity,
                                   "time_expressions": temporal_values, "location_text": location_hint.group(1) if location_hint else None}
                    later_type = "CONSEQUENCE" if later_action in {"damage", "kill", "injure"} else ("RESPONSE" if later_action == "respond" else "OCCURRENCE")
                    candidates.append(ClaimCandidate(later_type, sentence, (span,), {"action": later_action, **later_roles}, "NEGATED" if later_negated else "AFFIRMED", "NEGATED" if later_negated else base_effective_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "HIGH" if not uncertainty else "MEDIUM"))

            if quantity:
                quantity_negated = _is_negated(sentence, quantity_start)
                candidates.append(ClaimCandidate("QUANTITATIVE", sentence, (span,), {"quantity": quantity}, "NEGATED" if quantity_negated else "AFFIRMED", "NEGATED" if quantity_negated else base_effective_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "HIGH"))

            for tm in _TEMPORAL.finditer(sentence):
                expr = tm.group()
                time_negated = _is_negated(sentence, tm.start())
                normalized = None
                precision = "PERIOD" if re.search(r"morning|afternoon|evening|night", expr, re.I) else "DAY"
                try:
                    if re.fullmatch(r"\d{1,2}:\d{2}\s*UTC", expr, re.I):
                        normalized = expr.upper().replace(" ", "")
                        precision = "MINUTE"
                    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?:\s*UTC)?", expr, re.I):
                        normalized = datetime.fromisoformat(expr.upper().replace(" UTC", "+00:00").replace("Z", "+00:00")).isoformat()
                        precision = "MINUTE"
                    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", expr):
                        normalized = date.fromisoformat(expr).isoformat()
                    elif re.fullmatch(r"[A-Za-z]+\s+\d{1,2},\s*\d{4}", expr):
                        normalized = datetime.strptime(expr, "%B %d, %Y").date().isoformat()
                except ValueError:
                    normalized = None
                candidates.append(ClaimCandidate("TIME", sentence, (span,), {"original": expr, "normalized": normalized, "precision": precision, "approximate": normalized is None}, "NEGATED" if time_negated else "AFFIRMED", "NEGATED" if time_negated else base_effective_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "MEDIUM"))

            location = location_hint
            if location:
                location_negated = _is_negated(sentence, location.start())
                candidates.append(ClaimCandidate("LOCATION", sentence, (span,), {"location_text": location.group(1)}, "NEGATED" if location_negated else "AFFIRMED", "NEGATED" if location_negated else base_effective_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "MEDIUM"))

            state_match = re.search(r"\b(?:ongoing|remains? operational|collapsed|ceased|operational|underway|continues?)\b", low)
            if state_match:
                state_negated = _is_negated(sentence, state_match.start())
                candidates.append(ClaimCandidate("STATUS", sentence, (span,), {"state_expression": state_match.group()}, "NEGATED" if state_negated else "AFFIRMED", "NEGATED" if state_negated else base_effective_status, effective_epistemic, attribution_type, attribution, "UNKNOWN", "MEDIUM"))

    # Collapse only identical normalized signatures; retain each separate source span.
    collapsed: dict[str, ClaimCandidate] = {}
    for candidate in candidates:
        key = candidate.identity
        if key in collapsed:
            prior = collapsed[key]
            spans = tuple(dict.fromkeys((*prior.spans, *candidate.spans)))
            collapsed[key] = ClaimCandidate(prior.type, prior.statement, spans, prior.normalized, prior.polarity,
                                             prior.status, prior.epistemic_status, prior.attribution_type,
                                             prior.attribution, prior.intent_label, prior.extraction_confidence)
        else:
            collapsed[key] = candidate
    return list(collapsed.values())


async def persist_document_claims(conn, document_id) -> int:
    from psycopg.types.json import Jsonb
    doc = await (await conn.execute("SELECT id,incident_id,title,excerpt,published_at FROM documents WHERE id=%s", (document_id,))).fetchone()
    if not doc or not doc["incident_id"]:
        return 0
    candidates = DeterministicClaimExtractor().extract(doc["title"], doc["excerpt"], doc["published_at"])
    for candidate in candidates:
        if candidate.type not in CLAIM_TYPES or candidate.polarity not in POLARITIES or candidate.epistemic_status not in EPISTEMIC:
            continue
        if not candidate.statement.strip() or not candidate.spans:
            continue
        span = candidate.spans[0]
        if candidate.attribution_type not in ATTRIBUTION_TYPES or candidate.intent_label not in {"REPORTED_INTENT", "INFERENCE", "SPECULATION", "UNKNOWN"}:
            continue
        quantity = candidate.normalized.get("quantity")
        if quantity and quantity.get("operator") not in QUANTITY_OPERATORS:
            continue
        if any(s.character_start < 0 or s.character_end > len(doc["title"] if s.text_field == "TITLE" else (doc["excerpt"] or ""))
               or (doc["title"] if s.text_field == "TITLE" else (doc["excerpt"] or ""))[s.character_start:s.character_end] != s.source_text for s in candidate.spans):
            continue
        canonical_key = "extract:" + candidate.identity
        row = None
        if candidate.type == "OCCURRENCE" and any(s.text_field == "TITLE" and s.source_text == doc["title"] for s in candidate.spans):
            legacy = await (await conn.execute(
                "SELECT c.id FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id "
                "WHERE c.incident_id=%s AND cs.document_id=%s AND c.type='OCCURRENCE' AND c.statement=%s AND c.canonical_key IS NULL LIMIT 1",
                (doc["incident_id"], document_id, doc["title"]),
            )).fetchone()
            if legacy:
                row = await (await conn.execute(
                    "UPDATE claims SET status=%s,intent_label=%s,canonical_key=%s,normalized_representation=%s,polarity=%s,"
                    "epistemic_status=%s,attribution_type=%s,attribution=%s,extraction_method='DETERMINISTIC_RULES',"
                    "extraction_confidence=%s,confidence_explanation='Claim truth remains unassessed; extraction confidence describes text classification only.',updated_at=now() "
                    "WHERE id=%s RETURNING id",
                    (candidate.status, candidate.intent_label, canonical_key, Jsonb(candidate.normalized), candidate.polarity,
                     candidate.epistemic_status, candidate.attribution_type, Jsonb(candidate.attribution),
                     candidate.extraction_confidence, legacy["id"]),
                )).fetchone()
        if not row:
            row = await (await conn.execute(
                "INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation,intent_label,canonical_key,normalized_representation,polarity,epistemic_status,attribution_type,attribution,extraction_method,extraction_confidence) "
                "VALUES(%s,%s,%s,%s,'UNVERIFIED','Claim truth remains unassessed; extraction confidence describes text classification only.',%s,%s,%s,%s,%s,%s,%s,'DETERMINISTIC_RULES',%s) "
                "ON CONFLICT(incident_id,canonical_key) DO UPDATE SET statement=EXCLUDED.statement,normalized_representation=EXCLUDED.normalized_representation,updated_at=now() RETURNING id",
                (doc["incident_id"], candidate.statement, candidate.type, candidate.status, candidate.intent_label,
                 canonical_key, Jsonb(candidate.normalized), candidate.polarity, candidate.epistemic_status,
                 candidate.attribution_type, Jsonb(candidate.attribution), candidate.extraction_confidence),
            )).fetchone()
        claim_id = row["id"]
        await conn.execute("INSERT INTO claim_sources(claim_id,document_id,provenance_note) VALUES(%s,%s,'Deterministic document claim extraction') ON CONFLICT DO NOTHING", (claim_id, document_id))
        for source_span in candidate.spans:
            await conn.execute(
                "INSERT INTO claim_source_spans(claim_id,document_id,text_field,character_start,character_end,source_text) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(claim_id,document_id,text_field,character_start,character_end) DO NOTHING",
                (claim_id, document_id, source_span.text_field, source_span.character_start, source_span.character_end, source_span.source_text),
            )
        roles = candidate.normalized
        for source_span in candidate.spans:
            mention_rows = await (await conn.execute(
                "SELECT m.entity_id,m.surface_text,m.character_start,m.character_end,m.entity_type,e.canonical_name FROM document_entity_mentions m JOIN entities e ON e.id=m.entity_id WHERE m.document_id=%s AND m.text_field=%s AND m.entity_id IS NOT NULL AND m.character_start >= %s AND m.character_end <= %s",
                (document_id, source_span.text_field, source_span.character_start, source_span.character_end),
            )).fetchall()
            for mention in mention_rows:
                role = next((k.upper() for k, v in roles.items() if v == mention["canonical_name"] and k in {"actor", "object", "target", "location"}), None)
                location_text = roles.get("location_text")
                if role is None and location_text and any(m.entity_name == mention["canonical_name"] for m in extract_mentions(location_text, "")):
                    role = "LOCATION"
                role = role or "MENTIONED"
                await conn.execute("INSERT INTO claim_entities(claim_id,entity_id,role) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (claim_id, mention["entity_id"], role))
    return len(candidates)
