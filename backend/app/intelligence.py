"""Conservative deterministic helpers. No model output is treated as ground truth."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))


def content_hash(title: str, summary: str) -> str:
    normalized = re.sub(r"\s+", " ", f"{title} {summary}".lower()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def event_fingerprint(actor: str, action: str, target: str = "", location: str = "", object_name: str = "") -> dict[str, str]:
    """Return normalized structured signals; embeddings never decide identity."""
    norm = lambda value: re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()
    return {key: norm(value) for key, value in {"actor": actor, "action": action, "target": target, "location": location, "object": object_name}.items() if value.strip()}


def candidate_score(left: dict, right: dict) -> tuple[int, list[str]]:
    strong = ("actor", "action", "target", "location", "object", "identifier")
    matched = [key for key in strong if left.get(key) and right.get(key) and left[key] == right[key]]
    # A candidate score supports retrieval/review only; it is never a merge decision.
    return len(matched), matched


def claims_incompatible(type_a: str, text_a: str, type_b: str, text_b: str) -> tuple[bool, str]:
    """Only detect narrow, explicit numeric conflicts with matching scope language."""
    if type_a != type_b or type_a != "QUANTITATIVE":
        return False, ""
    a, b = re.search(r"\b(\d[\d,.]*)\b", text_a), re.search(r"\b(\d[\d,.]*)\b", text_b)
    if not a or not b:
        return False, ""
    scope_a = re.sub(r"\b\d[\d,.]*\b", "", text_a.lower()).strip()
    scope_b = re.sub(r"\b\d[\d,.]*\b", "", text_b.lower()).strip()
    if scope_a != scope_b:
        return False, ""
    try:
        n_a, n_b = float(a.group(1).replace(",", "")), float(b.group(1).replace(",", ""))
    except ValueError:
        return False, ""
    if n_a != n_b:
        return True, f"Incompatible quantities reported for the same stated scope ({n_a:g} vs {n_b:g}); unresolved."
    return False, ""


def confidence_summary(independent_support: int, contradictions: int, direct: bool) -> tuple[str, str]:
    if contradictions:
        return "CONTESTED", f"{contradictions} unresolved contradictory claim(s); values have not been reconciled."
    if independent_support >= 2 and direct:
        return "HIGH", "Multiple independent evidence groups include direct evidence."
    if independent_support >= 2:
        return "MEDIUM", "Multiple independent evidence groups; directness is limited or unknown."
    if independent_support == 1:
        return "LOW", "One evidence group is available; independent corroboration is absent."
    return "UNVERIFIED", "No linked evidence is available."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
