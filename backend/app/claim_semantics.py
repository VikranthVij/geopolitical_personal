"""Conservative assertion semantics for relationship and escalation decisions.

These labels describe what is reported, never whether the report is true.
Unknown or mixed scope must not establish an executed military action.
"""
import re


def assertion_semantics(claim: dict) -> str:
    text = claim.get("statement", "") or ""
    status = {str(claim.get(k, "")).upper() for k in ("status", "epistemic_status")}
    if "DENIED" in status or re.search(r"\b(?:denied|denies|denying|refuted|no evidence)\b", text, re.I):
        return "DENIAL"
    if claim.get("polarity") == "NEGATED" or re.search(r"\b(?:(?:did|has|have|had|is|was|were|are|does|do) not|never)\b", text, re.I):
        return "NEGATED"
    if re.search(r"\b(?:if|may|might|could|potential|possible|possibly|would)\b", text, re.I):
        return "CONDITIONAL_POSSIBILITY"
    if re.search(r"\b(?:consider\w*|weigh\w*|contemplat\w*)\b", text, re.I) or "?" in text:
        return "CONSIDERATION"
    if re.search(r"\b(?:plan|plans|planned|planning|prepare|prepares|prepared|preparing|preparation|preparations|contingency)\b", text, re.I):
        return "PLAN"
    if re.search(r"\bthreaten\w*\b", text, re.I):
        return "THREAT"
    if re.search(r"\bwarn\w*\b", text, re.I):
        return "WARNING"
    if re.search(r"\b(?:confirmed|approved|authorized|authorised|decided)\b.{0,60}\b(?:decision|military|attack|strike|deployment)\b", text, re.I):
        return "DECISION"
    if claim.get("type") == "INTENT" or re.search(r"\b(?:intend\w*|announced (?:an? )?intention|will)\b", text, re.I):
        return "INTENTION"
    if status & {"POSSIBLE", "UNCERTAIN", "SPECULATION"} or claim.get("intent_label") in {"SPECULATION", "INFERENCE"}:
        return "SPECULATION"
    if re.search(r"\breports? of\b[^.;!?]{0,80}\b(?:attack|strike|deployment)\b", text, re.I):
        return "REPORTED_OCCURRENCE"
    if re.search(r"\b(?:launched|attacked|struck|fired|deployed|retaliated|escalated|occurred|responded|announced|issued|rejected|imposed|collapsed|suspended|recalled|withdrawn|disrupted|killed)\b", text, re.I):
        reported = status & {"REPORTED", "ALLEGED"} or re.search(r"\b(?:reportedly|reported|according to)\b", text, re.I)
        return "REPORTED_OCCURRENCE" if reported else "ACTUAL_OCCURRENCE"
    return "UNKNOWN"
