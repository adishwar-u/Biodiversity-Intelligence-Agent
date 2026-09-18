"""Structured JSON input path — no UI required.

Usage:
    echo '{"soil_organic_carbon": 0.3, "rainfall_mm": 550, "land_use": "cropland"}' | python cli.py
"""
from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from agent.profile import EnvironmentalProfile
from agent.clarify import next_question
from agent.reason import filter_candidates, load_interventions, rank_candidates
from agent.respond import build_recommendations, maybe_llm_intro


def run(profile_dict: dict) -> None:
    profile = EnvironmentalProfile(**profile_dict)
    interventions = load_interventions()

    question = next_question(profile, interventions)
    if question:
        field, text = question
        print(f"[clarifying question — missing '{field}']\n{text}\n")
        print("(Continuing with the information given; unset fields are simply not used to filter.)\n")

    candidates = filter_candidates(profile, interventions)
    ranked = rank_candidates(profile, candidates)
    recommendations = build_recommendations(ranked)

    print(maybe_llm_intro(profile, recommendations))
    print()
    for rec in recommendations:
        print(f"### {rec.action}")
        print(f"Why: {rec.mechanism}")
        print(f"Horizon: {rec.horizon} | Confidence: {rec.confidence}")
        print("Cascade:")
        for line in rec.cascade[:3]:
            print(f"  {line}")
        print("Metrics improved:")
        for m in rec.metrics_improved:
            print(f"  - {m.metric}: {m.delta} ({m.horizon}, {m.confidence} confidence)")
        print("Tradeoffs:")
        for t in rec.tradeoffs:
            print(f"  - {t}")
        print("Sources:")
        for s in rec.sources:
            print(f"  - {s.title} ({s.org}, {s.year})")
        print()


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if not raw:
        print("No input on stdin. Pipe a JSON object, e.g.:")
        print('  echo \'{"soil_organic_carbon": 0.3, "rainfall_mm": 550, "land_use": "cropland"}\' | python cli.py')
        sys.exit(1)
    run(json.loads(raw))
