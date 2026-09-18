"""Structured output contract + citation validation + optional LLM polish.

The schema enforces that every recommendation carries the four elements the
brief requires: what to do, why it works, which metric improves, which
source backs it. A recommendation with zero valid sources after validation
is dropped rather than rendered.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from pydantic import BaseModel

from agent.profile import EnvironmentalProfile
from agent.reason import cascade_for
from kb.retriever import get_retriever


class Source(BaseModel):
    title: str
    org: str
    year: Optional[int] = None
    locator: Optional[str] = None


class MetricDelta(BaseModel):
    metric: str
    delta: str
    horizon: Literal["short", "medium", "long"]
    confidence: Literal["high", "medium", "low"]


class Recommendation(BaseModel):
    action: str
    mechanism: str
    cascade: list[str]
    metrics_improved: list[MetricDelta]
    tradeoffs: list[str]
    horizon: Literal["short", "medium", "long"]
    confidence: Literal["high", "medium", "low"]
    sources: list[Source]
    evidence: list[Source] = []  # supporting corpus excerpts, separate from the curated Store B sources


_HORIZON_ORDER = {"short": 0, "medium": 1, "long": 2}
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def validate_sources(interv: dict) -> list[Source]:
    """Citation validator: only pass through sources that are actually
    present on the curated row. This is the choke point that guarantees no
    fabricated citation reaches the response — nothing downstream may add a
    source that wasn't already here."""
    sources = []
    for s in interv.get("sources", []):
        if s.get("title") and s.get("org"):
            sources.append(Source(title=s["title"], org=s["org"], year=s.get("year"), locator=s.get("locator")))
    return sources


def build_recommendation(interv: dict) -> Optional[Recommendation]:
    sources = validate_sources(interv)
    if not sources:
        return None  # no valid citation -> do not render, per design rule

    effects = interv.get("effects", [])
    if not effects:
        return None

    metrics_improved = [
        MetricDelta(metric=e["metric"], delta=e["delta"], horizon=e["horizon"], confidence=e["confidence"])
        for e in effects
    ]

    cascades = cascade_for(interv)
    cascade_lines = []
    for metric, paths in cascades.items():
        for path in paths[:2]:  # cap so one intervention doesn't dump the whole graph
            cascade_lines.append(path)  # path already starts with `metric`

    overall_horizon = min(effects, key=lambda e: _HORIZON_ORDER[e["horizon"]])["horizon"]
    overall_confidence = min(effects, key=lambda e: _CONFIDENCE_ORDER[e["confidence"]])["confidence"]

    retriever = get_retriever()
    evidence_docs = retriever.search(f"{interv['name']} {' '.join(e['metric'] for e in effects)}", top_k=2)
    evidence = [Source(title=d.title, org=d.org, year=d.year) for d in evidence_docs]

    return Recommendation(
        action=interv["name"],
        mechanism=interv["mechanism"],
        cascade=cascade_lines,
        metrics_improved=metrics_improved,
        tradeoffs=interv.get("tradeoffs", []),
        horizon=overall_horizon,
        confidence=overall_confidence,
        sources=sources,
        evidence=evidence,
    )


def build_recommendations(interventions: list[dict]) -> list[Recommendation]:
    out = []
    for interv in interventions:
        rec = build_recommendation(interv)
        if rec:
            out.append(rec)
    return out


def _llm_prompt(profile: EnvironmentalProfile, recommendations: list[Recommendation]) -> str:
    actions = ", ".join(r.action for r in recommendations)
    profile_desc = "; ".join(profile.summary_lines()) or "an unspecified plot"
    return (
        f"In 2-3 plain sentences, introduce these biodiversity interventions "
        f"for a plot described as: {profile_desc}. Interventions: {actions}. "
        f"Do not invent any numbers, statistics, or sources — just set context."
    )


def _groq_intro(prompt: str) -> Optional[str]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
            max_tokens=500,  # gpt-oss spends part of the budget on hidden reasoning tokens
            messages=[{"role": "user", "content": prompt}],
        )
        content = (completion.choices[0].message.content or "").strip()
        return content or None
    except Exception:
        return None


def _anthropic_intro(prompt: str) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


def maybe_llm_intro(profile: EnvironmentalProfile, recommendations: list[Recommendation]) -> str:
    """If GROQ_API_KEY or ANTHROPIC_API_KEY is set, ask the model for a
    one-paragraph natural intro summarizing the recommendations (Groq tried
    first). Otherwise fall back to a plain template. Either way, no numbers
    or citations pass through the LLM — those always come straight from
    Store B."""
    if not recommendations:
        return _template_intro(profile, recommendations)

    prompt = _llm_prompt(profile, recommendations)
    text = _groq_intro(prompt) or _anthropic_intro(prompt)
    return text or _template_intro(profile, recommendations)


def _template_intro(profile: EnvironmentalProfile, recommendations: list[Recommendation]) -> str:
    if not recommendations:
        return "No interventions in the knowledge base matched what's known about this land yet."
    desc = ", ".join(profile.summary_lines()) or "the land you described"
    return (
        f"Based on {desc}, here are {len(recommendations)} evidence-backed interventions, "
        f"ranked by fit, effect size and confidence:"
    )
