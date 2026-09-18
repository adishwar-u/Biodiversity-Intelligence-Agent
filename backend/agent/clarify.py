"""Ask for the missing field that most changes the answer, not the missing
field that happens to come first. One question per turn, always with an
escape hatch.
"""
from __future__ import annotations

from agent.profile import CRITICAL_FIELDS, EnvironmentalProfile

QUESTION_TEMPLATES = {
    "soil_organic_carbon": (
        "What's the soil organic carbon (SOC) on this land, roughly, as a percentage? "
        "If you're not sure, I can work from typical values for your region instead."
    ),
    "rainfall_mm": (
        "What's the mean annual rainfall for this land, in mm? "
        "If you're not sure, I can work from typical values for your region instead."
    ),
    "land_use": (
        "How is the land currently used — cropland, degraded/barren, pasture, grassland, or forest? "
        "If you're not sure, I can work from typical values for your region instead."
    ),
    "region": (
        "Roughly which region or agro-climatic zone is this land in? "
        "That lets me fall back on typical values for anything else you're unsure of."
    ),
}


def next_question(profile: EnvironmentalProfile, interventions: list[dict]) -> tuple[str, str] | None:
    """Pick the missing field whose answer most evenly splits the candidate
    interventions — the question that actually changes the recommendation.
    Returns (field_name, question_text) or None if nothing is missing.
    """
    best_field, best_score = None, -1
    for field in CRITICAL_FIELDS:
        if getattr(profile, field) is not None:
            continue
        gated = [i for i in interventions if field in i.get("preconditions", {})]
        score = min(len(gated), len(interventions) - len(gated))
        if score > best_score:
            best_field, best_score = field, score

    if best_field is None:
        # Nothing scored (e.g. only 'region' missing, which gates nothing directly)
        missing = profile.missing_critical_fields()
        best_field = missing[0] if missing else None

    if best_field is None:
        return None
    return best_field, QUESTION_TEMPLATES[best_field]
