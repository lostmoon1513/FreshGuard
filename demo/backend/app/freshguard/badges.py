"""Turn a FreshGuard Verification (real SDK object or mock) into the badge the UI shows.

Mapping comes from INTEGRATION_GUIDE.md section 7:
  fresh -> green "Verified current"      stale -> red "Out of date" (+ correction + source url)
  potentially_stale -> amber             unverifiable -> grey "Could not verify"
  pending/running -> spinner "Checking…" failed / no job -> no badge
"""
from typing import Any


def _get(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


LABEL_BADGES = {
    "fresh": ("green", "Verified current"),
    "stale": ("red", "Out of date"),
    "potentially_stale": ("amber", "May be out of date"),
    "unverifiable": ("grey", "Could not verify"),
}


def checking_badge() -> dict:
    return {"state": "checking", "color": "blue", "text": "Checking…"}


def unavailable_badge(error: str | None = None) -> dict:
    """Verification could not run (failed job, FreshGuard unreachable, bad key...).

    The user must always see whether an answer was verified, so this is a visible grey
    "Not verified" badge with the reason, never a missing badge."""
    return {"state": "unavailable", "color": "grey", "text": "Not verified",
            "error": error or "Verification unavailable", "claims": []}


def _evidence_summary(v) -> tuple[list[dict], str | None]:
    claims_out, first_url = [], None
    claims = _get(v, "claims", []) or []
    # Prefer the evidence of the worst claim for the headline source link.
    order = {"stale": 0, "potentially_stale": 1, "unverifiable": 2, "fresh": 3}
    for claim in sorted(claims, key=lambda c: order.get(_get(c, "label"), 9)):
        ev_list = _get(claim, "evidence", []) or []
        ev_out = [
            {"url": _get(e, "url"), "stance": _get(e, "stance"),
             "quoted_span": _get(e, "quoted_span"), "tier": _get(e, "tier")}
            for e in ev_list
        ]
        if first_url is None and ev_out:
            contradicting = [e for e in ev_out if e["stance"] == "contradicts"]
            first_url = (contradicting or ev_out)[0]["url"]
        claims_out.append({"text": _get(claim, "text"), "label": _get(claim, "label"),
                           "reasoning": _get(claim, "reasoning"), "evidence": ev_out})
    return claims_out, first_url


def badge_from_verification(v) -> dict:
    status = _get(v, "status")
    if status in ("pending", "running"):
        return checking_badge()
    if status == "failed":
        return unavailable_badge(_get(v, "error") or "The verification run failed")

    label = _get(v, "label")
    color, text = LABEL_BADGES.get(label, ("grey", "Could not verify"))
    claims, source_url = _evidence_summary(v)
    return {
        "state": label if label in LABEL_BADGES else "unverifiable",
        "color": color,
        "text": text,
        "confidence": _get(v, "confidence"),
        "suggested_correction": _get(v, "suggested_correction") if label == "stale" else None,
        "source_url": source_url if label == "stale" else None,
        "claims": claims,
    }
