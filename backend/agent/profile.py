"""Persistent facts about the land being discussed, plus rule-based extraction
from free text. No LLM required to run — this keeps the MVP usable with zero
API key configured.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

LandUse = Literal["cropland", "degraded", "pasture", "grassland", "forest"]
Slope = Literal["flat", "gentle", "moderate", "steep"]

# Fields the clarifying-question gate blocks on. `region` is deliberately not
# here: no intervention's preconditions key on region (see data/interventions.json),
# so it has zero effect on filtering — it only unlocks the "use typical values"
# escape hatch, which is handled separately and doesn't need to block the main flow.
CRITICAL_FIELDS = ["soil_organic_carbon", "rainfall_mm", "land_use"]

# Typical values per Indian agro-climatic zone, used only when the user
# explicitly invokes the escape hatch ("use typical values").
REGION_DEFAULTS: dict[str, dict] = {
    "semi-arid deccan": {"rainfall_mm": 650, "soil_organic_carbon": 0.35, "land_use": "cropland"},
    "indo-gangetic plains": {"rainfall_mm": 1000, "soil_organic_carbon": 0.5, "land_use": "cropland"},
    "arid rajasthan": {"rainfall_mm": 300, "soil_organic_carbon": 0.2, "land_use": "degraded"},
    "western ghats": {"rainfall_mm": 2500, "soil_organic_carbon": 1.2, "land_use": "forest"},
    "central highlands": {"rainfall_mm": 900, "soil_organic_carbon": 0.45, "land_use": "cropland"},
    "coastal andhra": {"rainfall_mm": 1100, "soil_organic_carbon": 0.55, "land_use": "cropland"},
    "north-east hills": {"rainfall_mm": 2000, "soil_organic_carbon": 1.0, "land_use": "forest"},
    "kutch": {"rainfall_mm": 400, "soil_organic_carbon": 0.15, "land_use": "degraded"},
}

# Generic climate-zone words captured into `region` even without a specific named
# zone (e.g. "region: semi-arid"). These have no entry in REGION_DEFAULTS, so
# apply_region_defaults() simply won't find typical values for them — but they
# still show up in the profile summary instead of being silently dropped.
_GENERIC_REGION_KEYWORDS = [
    "semi-arid", "semi arid", "arid", "sub-humid", "subhumid", "humid",
    "tropical", "temperate", "coastal", "highland",
]


class EnvironmentalProfile(BaseModel):
    soil_organic_carbon: Optional[float] = None  # percent, e.g. 0.35
    rainfall_mm: Optional[float] = None           # mean annual, mm
    land_use: Optional[LandUse] = None
    slope: Optional[Slope] = None
    region: Optional[str] = None
    notes: list[str] = []

    def missing_critical_fields(self) -> list[str]:
        return [f for f in CRITICAL_FIELDS if getattr(self, f) is None]

    def apply_region_defaults(self) -> list[str]:
        """Fill any still-missing fields from the matched region's typical values.
        Returns the list of fields that were filled."""
        if not self.region:
            return []
        key = self.region.strip().lower()
        defaults = REGION_DEFAULTS.get(key)
        if not defaults:
            return []
        filled = []
        for field, value in defaults.items():
            if getattr(self, field) is None:
                setattr(self, field, value)
                filled.append(field)
        return filled

    def summary_lines(self) -> list[str]:
        lines = []
        if self.region:
            lines.append(f"Region: {self.region}")
        if self.rainfall_mm is not None:
            lines.append(f"Rainfall: {self.rainfall_mm:.0f} mm/yr")
        if self.soil_organic_carbon is not None:
            lines.append(f"Soil organic carbon: {self.soil_organic_carbon:.2f}%")
        if self.land_use:
            lines.append(f"Land use: {self.land_use}")
        if self.slope:
            lines.append(f"Slope: {self.slope}")
        return lines


_RAINFALL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.IGNORECASE)
_SOC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:soc|soil organic carbon|organic carbon)?", re.IGNORECASE)
_SOC_LABEL_RE = re.compile(r"(?:soc|soil organic carbon|organic carbon)\D{0,10}(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)

# Qualitative rainfall ("Rainfall: low", "low rainfall region") mapped to a
# representative mm value, since real-world descriptions rarely come as a
# bare number. Numeric mentions (_RAINFALL_RE) always take priority when both appear.
_RAINFALL_QUALITATIVE_VALUES = {
    "very low": 250, "scanty": 250, "scarce": 250,
    "low": 400,
    "moderate": 750, "medium": 750,
    "high": 1400, "heavy": 1400,
    "very high": 2000,
}
_RAINFALL_QUAL_PATTERN = "|".join(sorted(_RAINFALL_QUALITATIVE_VALUES, key=len, reverse=True))
_RAINFALL_QUAL_AFTER_RE = re.compile(rf"rainfall\D{{0,15}}\b({_RAINFALL_QUAL_PATTERN})\b", re.IGNORECASE)
_RAINFALL_QUAL_BEFORE_RE = re.compile(rf"\b({_RAINFALL_QUAL_PATTERN})\b\D{{0,10}}rainfall", re.IGNORECASE)

_LAND_USE_KEYWORDS = {
    "cropland": ["cropland", "crop land", "farmland", "arable", "wheat", "rice", "maize", "farm field", "cultivated"],
    "degraded": ["degraded", "barren", "wasteland", "eroded", "denuded"],
    "pasture": ["pasture", "grazing land", "livestock land"],
    "grassland": ["grassland", "rangeland", "savanna"],
    "forest": ["forest", "woodland", "tree cover"],
}

_SLOPE_KEYWORDS = {
    "flat": ["flat", "level"],
    "gentle": ["gentle slope", "gently sloping"],
    "moderate": ["moderate slope"],
    "steep": ["steep", "hilly"],
}

_ESCAPE_HATCH_PHRASES = [
    "not sure", "don't know", "dont know", "no idea", "unsure",
    "use typical", "typical values", "typical for", "your best guess",
    "go for it", "just guess", "you decide", "you choose", "proceed",
    "whatever's typical", "whatever is typical", "up to you", "your call",
]


def wants_escape_hatch(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _ESCAPE_HATCH_PHRASES)


# Short plain-English answers for "what is X" style questions asked mid-conversation.
GLOSSARY: dict[str, str] = {
    "soil_organic_carbon": (
        "Soil organic carbon (SOC) is the carbon stored in soil from decomposed plant "
        "and animal matter. It's usually given as a percentage of soil weight — most "
        "cropland runs roughly 0.2-1.5%. Higher SOC generally means better water "
        "retention and soil health."
    ),
    "rainfall_mm": (
        "Mean annual rainfall in millimetres — the total rain a location typically "
        "gets over a year. Semi-arid regions might see 400-700mm; wetter regions can "
        "exceed 2000mm."
    ),
    "land_use": (
        "How the land is currently used: cropland (farmed), degraded/barren, pasture "
        "(grazed), grassland, or forest."
    ),
    "slope": (
        "How steep the land is: flat, gentle, moderate, or steep. It affects runoff "
        "and erosion risk, and some interventions only make sense above or below a "
        "certain slope."
    ),
    "region": (
        "The broader area or agro-climatic zone this land is in — e.g. semi-arid "
        "deccan, arid rajasthan, western ghats. Naming a region lets me fall back on "
        "typical values for anything else you're unsure of."
    ),
}

_GLOSSARY_KEYWORDS = {
    "soil_organic_carbon": ["soil organic carbon", "soc"],
    "rainfall_mm": ["rainfall", "rain fall", "precipitation"],
    "land_use": ["land use", "landuse"],
    "slope": ["slope"],
    "region": ["region", "agro-climatic", "agroclimatic", "agro climatic", "zone"],
}

_QUESTION_STARTERS = (
    "what is", "what's", "whats", "what are", "what does", "explain",
    "define", "meaning of", "what mean", "what do you mean",
)


def detect_glossary_question(text: str) -> Optional[str]:
    """Recognize a genuine question about a field ("what is SOC?") so it can be
    answered instead of silently re-asking the same clarifying question."""
    lowered = text.lower().strip()
    if "?" not in lowered and not lowered.startswith(_QUESTION_STARTERS):
        return None
    for field, keywords in _GLOSSARY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return field
    return None


def extract_updates(text: str) -> dict:
    """Rule-based extraction of profile fields from a free-text message.
    Deterministic and dependency-free — no LLM call required to run the demo."""
    updates: dict = {}
    lowered = text.lower()

    rainfall_match = _RAINFALL_RE.search(text)
    if rainfall_match:
        updates["rainfall_mm"] = float(rainfall_match.group(1))
    else:
        qual_match = _RAINFALL_QUAL_AFTER_RE.search(text) or _RAINFALL_QUAL_BEFORE_RE.search(text)
        if qual_match:
            updates["rainfall_mm"] = float(_RAINFALL_QUALITATIVE_VALUES[qual_match.group(1).lower()])

    soc_match = _SOC_LABEL_RE.search(text) or _SOC_RE.search(text)
    if soc_match:
        updates["soil_organic_carbon"] = float(soc_match.group(1))

    for land_use, keywords in _LAND_USE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            updates["land_use"] = land_use
            break

    for slope, keywords in _SLOPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            updates["slope"] = slope
            break

    for region_key in REGION_DEFAULTS:
        if region_key in lowered:
            updates["region"] = region_key
            break
    else:
        for generic in _GENERIC_REGION_KEYWORDS:
            if generic in lowered:
                updates["region"] = generic
                break

    return updates
