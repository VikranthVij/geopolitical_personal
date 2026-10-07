"""Bounded deterministic extraction and persistence for explicit evidence references."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit


EvidenceKind = str
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OFFICIAL_STATEMENT", re.compile(r"\b(?:(?:official|government|military|ministry|presidential)\s+)?(?:official\s+)?(?:statement|communique|press release)(?:\s+(?:released|issued|published))?\b|\b(?:the\s+)?(?:ministry|government|military)\s+(?:released|issued)\s+(?:an?\s+)?(?:official\s+)?statement\b", re.I)),
    ("SATELLITE_IMAGERY", re.compile(r"\b(?:(?:Maxar|Planet(?:\s+Labs)?|Airbus)\s+)?satellite\s+(?:imagery|images?|photographs?)(?:\s+(?:(?:reviewed|verified|analy[sz]ed|examined|obtained|provided|released)(?:\s+by\s+[\w .'-]{1,45})?|reportedly))?\b|\b(?:Maxar|Planet(?:\s+Labs)?|Airbus)\s+imagery\b", re.I)),
    ("GEOSPATIAL_DATA", re.compile(r"\b(?:geospatial\s+(?:data|analysis)|geolocation\s+data|geolocated\s+images?)\b", re.I)),
    ("VIDEO", re.compile(r"\b(?:video\s+footage|video\s+recording|footage|video)\s*(?:verified\s+by\s+[\w .'-]{1,40})?\b", re.I)),
    ("PHOTOGRAPH", re.compile(r"\b(?:photographs?|photos)\s*(?:verified\s+by\s+[\w .'-]{1,40})?\b", re.I)),
    ("FLIGHT_TRACKING", re.compile(r"\b(?:flight\s+tracking|flight\s+tracking\s+data|aircraft\s+tracking)\s*(?:data)?\b", re.I)),
    ("SHIP_TRACKING", re.compile(r"\b(?:ship|vessel|maritime)\s+tracking\s+(?:data|records?)\b|\bAIS\s+(?:data|tracking)\b", re.I)),
    ("RADAR_DATA", re.compile(r"\b(?:radar\s+(?:data|records?|tracking)|air\s+defen[cs]e\s+tracking\s+data)\b", re.I)),
    ("EYEWITNESS", re.compile(r"\b(?:eyewitness(?:es)?|witness(?:es)?(?:\s+(?:on\s+the\s+ground|at\s+the\s+scene))?)\b", re.I)),
    ("PHYSICAL_EVIDENCE", re.compile(r"\b(?:debris|fragments?|wreckage|physical\s+evidence|munitions\s+remnants?)\b", re.I)),
    ("OPEN_SOURCE_ANALYSIS", re.compile(r"\b(?:OSINT\s+(?:analysts?|analysis)|open[- ]source\s+(?:analysts?|analysis)|analysts?\s+(?:identified|geolocated|verified|analy[sz]ed))\b", re.I)),
    ("DOCUMENT", re.compile(r"\b(?:documents?|records?|filings?|logs?)\s+(?:reviewed|obtained|released|published|seen|examined)\s+by\s+[\w .'-]{1,45}\b|\b(?:documents?|records?)\s+(?:show|indicate|reveal)\b", re.I)),
    ("DOCUMENT", re.compile(r"\b(?:cited|quot(?:ed|ing)|relied on|based on)\s+(?:(?:the|a|an)\s+)?[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3}'?s?\s+(?:report|article|investigation|analysis)\b", re.I)),
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_IDENTIFIER = re.compile(r"\b(?:image|imagery|satellite\s+image|video|document|flight\s+data|radar\s+data|tracking\s+data)\s*(?:id|identifier|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\b", re.I)
_REFERENCE_URL = re.compile(r"https?://[^\s)\]}>\"']+", re.I)


@dataclass(frozen=True)
class EvidenceSpan:
    text_field: str
    character_start: int
    character_end: int
    source_text: str


@dataclass(frozen=True)
class EvidenceCandidate:
    type: EvidenceKind
    description: str
    span: EvidenceSpan
    sentence: str
    directness: str = "UNKNOWN"
    attribution: dict = field(default_factory=dict)
    origin_reference: str | None = None
    referenced_source: str | None = None
    provider: str | None = None
    external_reference: str | None = None
    reference_url: str | None = None
    document_relation: str = "REFERENCES"
    claim_relation: str = "INCONCLUSIVE"
    negated: bool = False
    extraction_confidence: str = "MEDIUM"

    @property
    def identity_key(self) -> str | None:
        reference = self.external_reference or self.reference_url
        if not reference:
            return None
        normalized = re.sub(r"\s+", "", reference).casefold()
        if self.reference_url and not self.external_reference:
            parts = urlsplit(self.reference_url)
            normalized = urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path, parts.query, ""))
        return f"{self.type}:{normalized}"


class EvidenceExtractor(Protocol):
    def extract(self, title: str | None, excerpt: str | None) -> list[EvidenceCandidate]: ...


def _sentences(text: str):
    start = 0
    for match in _SENTENCE_SPLIT.finditer(text):
        yield start, match.start(), text[start:match.start()].strip()
        start = match.end()
    if start < len(text):
        yield start, len(text), text[start:].strip()


def _span_start(text: str, start: int) -> int:
    while start < len(text) and text[start].isspace():
        start += 1
    return start


def _attribution(sentence: str) -> tuple[dict, str | None]:
    by = re.search(r"\b(?:according to|cited by|reported by|verified by|reviewed by|provided by|released by|issued by)\s+([^,.;]{1,80})", sentence, re.I)
    nested = re.search(r"\b(?:reported|reports?)\s+that\s+(.*?\b(?:officials?|authorities|minister|spokesperson)\b)\s+(?:said|claimed|reported)\b", sentence, re.I)
    officials = re.search(r"\b((?:Iranian|Israeli|U\.S\.|American|Russian|Ukrainian|Chinese|government|military|defense|defence|ministry|presidential)\s+(?:officials?|authorities|military|government|ministry|spokesperson|statement))\s+(?:said|claimed|reported|released|issued|provided|shared)\b", sentence, re.I)
    analysts = re.search(r"\b(analysts?)\s+(?:believe|identified|geolocated|verified|analy[sz]ed)\b", sentence, re.I)
    speaker = nested.group(1).strip() if nested else by.group(1).strip() if by else officials.group(1).strip() if officials else analysts.group(1).strip() if analysts else None
    reported = bool(re.search(r"\b(?:reportedly|reported|according to|cited|quoting|based on|relied on|relies on)\b", sentence, re.I))
    attribution = {"speaker_text": speaker, "chain": sentence.strip()} if speaker or reported else {}
    return attribution, speaker


def _directness(sentence: str, kind: str) -> str:
    low = sentence.casefold()
    if re.search(r"\b(?:no|not|never|without)\b.{0,35}\b(?:evidence|imagery|video|footage|data|statement|witness|document)", low):
        return "UNKNOWN"
    if re.search(r"\b(?:derived from|based on|analysis of|analysts? (?:believe|identified|geolocated|verified|analy[sz]ed))\b", low):
        return "DERIVED"
    if re.search(r"\b(?:reportedly|according to|cited|quoting|reported that|officials? said|witnesses? said)\b", low):
        return "REPORTED"
    if re.search(r"\b(?:independently reviewed|directly observed|journalists? (?:saw|witnessed|observed)|witnessed|filmed|photographed|recorded by)", low):
        return "DIRECT"
    if kind == "SATELLITE_IMAGERY" and re.search(r"\b(?:reviewed|verified|examined)\s+(?:the\s+)?(?:satellite\s+)?imagery\b", low):
        return "REPORTED"
    if kind == "OFFICIAL_STATEMENT" and re.search(r"\b(?:released|issued|published)\b", low):
        return "DIRECT"
    # A bare reference such as “imagery shows” does not disclose who acquired or reviewed it.
    return "UNKNOWN"


def _claim_relation(sentence: str, negated: bool) -> str:
    if negated:
        return "INCONCLUSIVE"
    if re.search(r"\b(?:partially supports?|partly supports?|consistent with|in part supports?)\b", sentence, re.I):
        return "PARTIALLY_SUPPORTS"
    if re.search(r"\b(?:contradicts?|refutes?|disproves?|rules? out|undermines?|does not support)\b", sentence, re.I):
        return "CONTRADICTS"
    if re.search(r"\b(?:show(?:s|ed|ing)?|confirms?|corroborates?|supports?|demonstrates?|indicates?|reveals?)\b", sentence, re.I):
        return "SUPPORTS"
    return "INCONCLUSIVE"


class DeterministicEvidenceExtractor:
    """Extract explicit evidence references only; never infer truth or credibility."""

    def extract(self, title: str | None, excerpt: str | None) -> list[EvidenceCandidate]:
        output: list[EvidenceCandidate] = []
        for field_name, text in (("TITLE", title or ""), ("EXCERPT", excerpt or "")):
            for sentence_start, _, sentence in _sentences(text):
                if not sentence:
                    continue
                trim_start = _span_start(text, sentence_start)
                sentence_matches: list[tuple[re.Match[str], str]] = []
                for kind, pattern in _PATTERNS:
                    for match in pattern.finditer(sentence):
                        if any(match.start() < old.end() and match.end() > old.start() for old, _ in sentence_matches):
                            continue
                        sentence_matches.append((match, kind))
                sentence_matches.sort(key=lambda item: item[0].start())
                attribution, speaker = _attribution(sentence)
                negative = bool(re.search(r"\b(?:no|not|never|without|hasn't|have not|did not)\b.{0,50}\b(?:confirmed|confirm|show|shown|verified|verify|support|established)\b", sentence, re.I))
                for match, kind in sentence_matches:
                    absolute_start = trim_start + match.start()
                    absolute_end = trim_start + match.end()
                    provider_match = re.search(r"\b(Maxar|Planet(?:\s+Labs)?|Airbus)\b", sentence, re.I)
                    provider = provider_match.group(1) if provider_match and kind == "SATELLITE_IMAGERY" else None
                    id_match = _IDENTIFIER.search(sentence)
                    url_match = _REFERENCE_URL.search(sentence)
                    directness = _directness(sentence, kind)
                    if re.search(r"\b(?:cited|citing|quotes?|quoting|according to|reported that|reported\s+(?:Reuters|AP|Associated Press|AFP|BBC|CNN))\b", sentence, re.I):
                        document_relation = "CITES"
                    elif kind == "OPEN_SOURCE_ANALYSIS" and re.search(r"\b(?:imagery|geospatial|video|radar|tracking)\b", sentence, re.I):
                        document_relation = "DERIVED_FROM"
                    else:
                        document_relation = "REFERENCES"
                    origin = speaker if kind == "OFFICIAL_STATEMENT" else provider
                    publisher_ref = re.search(r"\b(?:cited|citing|reported|reporting|according to)\s+(Reuters|AP|Associated Press|AFP|BBC|CNN)\b", sentence, re.I)
                    output.append(EvidenceCandidate(
                        type=kind,
                        description=re.sub(r"\s+", " ", match.group()).strip(),
                        span=EvidenceSpan(field_name, absolute_start, absolute_end, text[absolute_start:absolute_end]),
                        sentence=sentence,
                        directness=directness,
                        attribution=attribution,
                        origin_reference=origin,
                        referenced_source=publisher_ref.group(1) if publisher_ref else None,
                        provider=provider,
                        external_reference=id_match.group(1) if id_match else None,
                        reference_url=url_match.group(0).rstrip(".,;:") if url_match else None,
                        document_relation=document_relation,
                        claim_relation=_claim_relation(sentence, negative),
                        negated=negative,
                        extraction_confidence="HIGH" if kind in {"OFFICIAL_STATEMENT", "SATELLITE_IMAGERY", "FLIGHT_TRACKING", "SHIP_TRACKING", "RADAR_DATA", "EYEWITNESS", "OPEN_SOURCE_ANALYSIS"} else "MEDIUM",
                    ))
        # Collapse duplicate regex hits on the exact source span, not paraphrases.
        unique = {}
        for candidate in output:
            key = (candidate.span.text_field, candidate.span.character_start, candidate.span.character_end, candidate.type)
            unique.setdefault(key, candidate)
        return list(unique.values())


async def persist_document_evidence(conn, document_id) -> int:
    """Persist evidence and provenance idempotently for a document with stored claims."""
    from psycopg.types.json import Jsonb

    doc = await (await conn.execute(
        "SELECT d.id,d.source_id,d.title,d.excerpt,d.published_at,s.name source_name "
        "FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=%s", (document_id,),
    )).fetchone()
    if not doc:
        return 0
    document_published_at = doc["published_at"].isoformat() if doc["published_at"] else None
    candidates = DeterministicEvidenceExtractor().extract(doc["title"], doc["excerpt"])
    persisted: dict[tuple[str, int, int, str], object] = {}
    for candidate in candidates:
        span = candidate.span
        source_text = doc["title"] if span.text_field == "TITLE" else (doc["excerpt"] or "")
        if span.character_start < 0 or span.character_end > len(source_text) or source_text[span.character_start:span.character_end] != span.source_text:
            continue
        identity_key = candidate.identity_key
        evidence = None
        if identity_key:
            evidence = await (await conn.execute(
                "SELECT id FROM evidence WHERE identity_key=%s", (identity_key,),
            )).fetchone()
        if not evidence:
            evidence = await (await conn.execute(
                "SELECT evidence_id AS id FROM evidence_source_spans WHERE document_id=%s AND text_field=%s "
                "AND character_start=%s AND character_end=%s AND source_text=%s LIMIT 1",
                (document_id, span.text_field, span.character_start, span.character_end, span.source_text),
            )).fetchone()
        if evidence:
            evidence_id = evidence["id"]
            await conn.execute(
                "UPDATE evidence SET description=%s,metadata=metadata || %s,origin_reference=COALESCE(origin_reference,%s),updated_at=now() WHERE id=%s",
                (candidate.description, Jsonb({"provider": candidate.provider, "external_reference": candidate.external_reference,
                                                "reference_url": candidate.reference_url, "negated_reference": candidate.negated}),
                 candidate.origin_reference, evidence_id),
            )
        else:
            independence_key = f"identity:{identity_key}" if identity_key else None
            evidence = await (await conn.execute(
                "INSERT INTO evidence(type,description,canonical_url,provenance,directness,independence_key,metadata,extraction_method,extraction_confidence,identity_key,origin_reference) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'DETERMINISTIC_RULES',%s,%s,%s) "
                "ON CONFLICT(identity_key) WHERE identity_key IS NOT NULL DO UPDATE SET updated_at=now() RETURNING id",
                (candidate.type, candidate.description, candidate.reference_url,
                 Jsonb({"reporting_document_id": str(document_id), "reporting_source": doc["source_name"], "attribution": candidate.attribution}),
                 candidate.directness, independence_key, Jsonb({"provider": candidate.provider,
                 "external_reference": candidate.external_reference, "reference_url": candidate.reference_url,
                 "negated_reference": candidate.negated, "normalized_type": candidate.type}),
                 candidate.extraction_confidence, identity_key, candidate.origin_reference),
            )).fetchone()
            evidence_id = evidence["id"]
        persisted[(span.text_field, span.character_start, span.character_end, candidate.type)] = evidence_id

        await conn.execute(
            "INSERT INTO evidence_documents(evidence_id,document_id,relation,directness,attribution,metadata) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(evidence_id,document_id,relation) DO UPDATE "
            "SET directness=EXCLUDED.directness,attribution=EXCLUDED.attribution,metadata=EXCLUDED.metadata",
            (evidence_id, document_id, candidate.document_relation, candidate.directness,
             Jsonb(candidate.attribution), Jsonb({"source_name": doc["source_name"], "origin_reference": candidate.origin_reference,
                                                  "referenced_source": candidate.referenced_source, "provider": candidate.provider,
                                                  "negated_reference": candidate.negated, "document_published_at": document_published_at})),
        )
        await conn.execute(
            "INSERT INTO evidence_source_spans(evidence_id,document_id,text_field,character_start,character_end,source_text) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(evidence_id,document_id,text_field,character_start,character_end) DO NOTHING",
            (evidence_id, document_id, span.text_field, span.character_start, span.character_end, span.source_text),
        )
        await conn.execute(
            "INSERT INTO evidence_sources(evidence_id,source_id,relation,reference_text) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (evidence_id, doc["source_id"], "REFERENCES", candidate.origin_reference),
        )
        if candidate.origin_reference:
            origin = await (await conn.execute("SELECT id FROM sources WHERE lower(name)=lower(%s)", (candidate.origin_reference,))).fetchone()
            if origin and origin["id"] != doc["source_id"]:
                await conn.execute(
                    "UPDATE evidence SET origin_source_id=COALESCE(origin_source_id,%s) WHERE id=%s",
                    (origin["id"], evidence_id),
                )
                await conn.execute(
                    "INSERT INTO evidence_sources(evidence_id,source_id,relation,reference_text) VALUES(%s,%s,'ORIGINATES_FROM',%s) ON CONFLICT DO NOTHING",
                    (evidence_id, origin["id"], candidate.origin_reference),
                )

        # A publisher name is recorded as cited provenance. Resolve it to a
        # particular document only when that document is already linked to this
        # exact evidence identity; publisher names alone are ambiguous.
        referenced = None
        if candidate.referenced_source:
            referenced = await (await conn.execute(
                "SELECT id FROM sources WHERE lower(name)=lower(%s) "
                "OR (%s='AP' AND lower(name)='associated press') ORDER BY name LIMIT 1",
                (candidate.referenced_source, candidate.referenced_source),
            )).fetchone()
        if referenced:
            await conn.execute(
                "INSERT INTO evidence_sources(evidence_id,source_id,relation,reference_text) VALUES(%s,%s,'CITES',%s) ON CONFLICT DO NOTHING",
                (evidence_id, referenced["id"], candidate.sentence),
            )
        resolve_shared_reference = bool(candidate.identity_key and re.search(r"\bsame\b", candidate.sentence, re.I))
        if candidate.document_relation == "CITES" and (referenced or resolve_shared_reference):
            conditions = "AND d.source_id=%s" if referenced else ""
            params = (evidence_id, referenced["id"], document_id) if referenced else (evidence_id, document_id)
            refs = await (await conn.execute(
                "SELECT DISTINCT ed.document_id FROM evidence_documents ed JOIN documents d ON d.id=ed.document_id "
                "WHERE ed.evidence_id=%s " + conditions + " AND d.id<>%s",
                params,
            )).fetchall()
            # Resolve only a unique matching reporting document; ambiguous lineage
            # remains attached to the publisher/evidence identity, not a guessed article.
            if len(refs) == 1:
                await conn.execute(
                    "UPDATE evidence_documents SET referenced_document_id=%s WHERE evidence_id=%s AND document_id=%s AND relation=%s",
                    (refs[0]["document_id"], evidence_id, document_id, candidate.document_relation),
                )

        claim_rows = await (await conn.execute(
            "SELECT c.id,c.type FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id "
            "JOIN claim_source_spans ss ON ss.claim_id=c.id AND ss.document_id=cs.document_id "
            "WHERE cs.document_id=%s AND ss.text_field=%s AND ss.source_text=%s",
            (document_id, span.text_field, candidate.sentence),
        )).fetchall()
        official_fallback = False
        if candidate.type == "OFFICIAL_STATEMENT":
            statement_claims = [c for c in claim_rows if c["type"] == "ATTRIBUTION"]
            if statement_claims:
                claim_rows = statement_claims
            else:
                # Existing claim extraction may retain only the event proposition. Keep
                # the link, but explicitly mark this statement inconclusive for that event.
                official_fallback = True
        same_sentence_items = [
            item for item in candidates
            if item.span.text_field == span.text_field and item.sentence == candidate.sentence
        ]
        ambiguous_link = len(same_sentence_items) != 1 or len(claim_rows) != 1
        for claim in claim_rows:
            relation = "INCONCLUSIVE" if official_fallback or ambiguous_link else candidate.claim_relation
            await conn.execute(
                "INSERT INTO claim_evidence(claim_id,evidence_id,relation,independence_group) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(claim_id,evidence_id) DO UPDATE SET relation=CASE WHEN claim_evidence.relation=EXCLUDED.relation THEN EXCLUDED.relation ELSE 'INCONCLUSIVE' END",
                (claim["id"], evidence_id, relation, f"identity:{identity_key}" if identity_key else f"evidence:{evidence_id}"),
            )
            await conn.execute(
                "INSERT INTO claim_evidence_sources(claim_id,evidence_id,document_id,relation) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(claim_id,evidence_id,document_id) DO UPDATE SET relation=EXCLUDED.relation",
                (claim["id"], evidence_id, document_id, relation),
            )
    # An explicitly described OSINT analysis can be derived from an explicitly
    # mentioned imagery/data item in the same sentence. The relationship is
    # recorded only when both candidates were extracted from this exact sentence.
    for candidate in candidates:
        if candidate.type != "OPEN_SOURCE_ANALYSIS":
            continue
        child_id = persisted.get((candidate.span.text_field, candidate.span.character_start, candidate.span.character_end, candidate.type))
        for parent_candidate in candidates:
            if parent_candidate.sentence != candidate.sentence or parent_candidate.type not in {"SATELLITE_IMAGERY", "GEOSPATIAL_DATA", "VIDEO", "RADAR_DATA", "FLIGHT_TRACKING", "SHIP_TRACKING"}:
                continue
            parent_id = persisted.get((parent_candidate.span.text_field, parent_candidate.span.character_start, parent_candidate.span.character_end, parent_candidate.type))
            if child_id and parent_id and child_id != parent_id:
                await conn.execute(
                    "INSERT INTO evidence_lineage(evidence_id,related_evidence_id,relation,reference_text) VALUES(%s,%s,'DERIVED_FROM',%s) ON CONFLICT DO NOTHING",
                    (child_id, parent_id, candidate.sentence),
                )
    return len(candidates)
