"""Candidate filtering (Store B) + graph traversal + ranking.

No LLM call happens in this module. Effect sizes come from the curated
table, never from a model — that's what makes a hallucinated number
structurally impossible.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.profile import EnvironmentalProfile
from kb.graph import trace

INTERVENTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "interventions.json"

_CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def load_interventions() -> list[dict]:
    return json.loads(INTERVENTIONS_PATH.read_text(encoding="utf-8"))


def _satisfies(value, condition) -> bool:
    if isinstance(condition, list) and len(condition) == 2 and all(isinstance(c, (int, float)) for c in condition):
        low, high = condition
        return low <= value <= high
    if isinstance(condition, list):
        return value in condition
    return value == condition


def filter_candidates(profile: EnvironmentalProfile, interventions: list[dict]) -> list[dict]:
    """Keep an intervention unless a precondition the profile has data for is
    violated. Preconditions the profile hasn't answered yet don't exclude a
    candidate — that's what makes them worth asking about."""
    candidates = []
    for interv in interventions:
        ok = True
        for field, condition in interv.get("preconditions", {}).items():
            value = getattr(profile, field, None)
            if value is None:
                continue
            if not _satisfies(value, condition):
                ok = False
                break
        if ok:
            candidates.append(interv)
    return candidates


def _score(interv: dict, profile: EnvironmentalProfile) -> float:
    effect_score = sum(_CONFIDENCE_WEIGHT.get(e.get("confidence", "low"), 1) for e in interv.get("effects", []))
    specificity_bonus = sum(
        1 for field in interv.get("preconditions", {}) if getattr(profile, field, None) is not None
    )
    tradeoff_penalty = 0.3 * len(interv.get("tradeoffs", []))
    return effect_score + specificity_bonus - tradeoff_penalty


def rank_candidates(profile: EnvironmentalProfile, candidates: list[dict], top_n: int = 4) -> list[dict]:
    return sorted(candidates, key=lambda i: _score(i, profile), reverse=True)[:top_n]


def cascade_for(interv: dict, depth: int = 3) -> dict[str, list[str]]:
    """Trace the causal graph downstream of each primary effect metric,
    returning {metric: [flat cascade path strings]}."""
    from kb.graph import flatten_chain

    result = {}
    for effect in interv.get("effects", []):
        metric = effect["metric"]
        nodes = trace(metric, depth=depth)
        paths = flatten_chain(nodes)
        if paths:
            result[metric] = paths
    return result


def get_recommendations(profile: EnvironmentalProfile, top_n: int = 4) -> list[dict]:
    interventions = load_interventions()
    candidates = filter_candidates(profile, interventions)
    ranked = rank_candidates(profile, candidates, top_n=top_n)
    return ranked
