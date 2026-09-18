"""JSON API for the React frontend.

Thin wrapper around the same agent/ and kb/ modules app.py and cli.py use —
no reasoning logic lives here, only session bookkeeping and serialization.
Sessions are kept in memory (fine for a local MVP demo; a restart clears
them, and there is no cross-process persistence).
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.clarify import next_question
from agent.profile import (
    GLOSSARY,
    REGION_DEFAULTS,
    EnvironmentalProfile,
    detect_glossary_question,
    extract_updates,
    wants_escape_hatch,
)
from agent.reason import filter_candidates, load_interventions, rank_candidates
from agent.respond import build_recommendations, maybe_llm_intro

app = FastAPI(title="Biodiversity Intelligence Agent API")

FRONTEND_URL = os.environ.get("FRONTEND_URL")

app.add_middleware(
    CORSMiddleware,
    # Matches any localhost/127.0.0.1 port, not just 5173 -- Vite falls back to
    # 5174, 5175, etc. whenever its default port is already taken.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    # Deployed frontend origin (e.g. the Vercel URL), set via env var since
    # it isn't known at code-writing time.
    allow_origins=[FRONTEND_URL] if FRONTEND_URL else [],
    allow_methods=["*"],
    allow_headers=["*"],
)

INTERVENTIONS = load_interventions()

WELCOME_TEXT = (
    "Tell me about a piece of land you want to improve for biodiversity — "
    "soil, rainfall, current land use, region, anything you know. "
    "I'll ask for anything critical that's missing, then give cited, "
    "multi-variable recommendations."
)


class Session:
    def __init__(self):
        self.profile = EnvironmentalProfile()
        self.messages: list[dict] = [{"role": "assistant", "text": WELCOME_TEXT, "recommendations": []}]
        self.rejected: set[str] = set()
        # True right after we've asked "which region?" purely to unlock typical-value
        # defaults — lets the very next region answer apply them immediately instead
        # of requiring the user to say "not sure" a second time.
        self.pending_escape_hatch: bool = False


SESSIONS: dict[str, Session] = {}


def _get_session(session_id: Optional[str]) -> tuple[str, Session]:
    if session_id and session_id in SESSIONS:
        return session_id, SESSIONS[session_id]
    new_id = session_id or str(uuid.uuid4())
    session = Session()
    SESSIONS[new_id] = session
    return new_id, session


def _serialize(session: Session) -> dict:
    profile = session.profile
    return {
        "profile": {
            "region": profile.region,
            "rainfall_mm": profile.rainfall_mm,
            "soil_organic_carbon": profile.soil_organic_carbon,
            "land_use": profile.land_use,
            "slope": profile.slope,
            "summary_lines": profile.summary_lines(),
            "missing_critical_fields": profile.missing_critical_fields(),
        },
        "messages": session.messages,
    }


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ResetRequest(BaseModel):
    session_id: Optional[str] = None


@app.get("/api/session")
def get_or_create_session(session_id: Optional[str] = None):
    sid, session = _get_session(session_id)
    return {"session_id": sid, **_serialize(session)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    sid, session = _get_session(req.session_id)
    profile = session.profile

    session.messages.append({"role": "user", "text": req.message, "recommendations": []})

    updates = extract_updates(req.message)
    for field, value in updates.items():
        setattr(profile, field, value)

    if session.pending_escape_hatch and profile.region:
        session.pending_escape_hatch = False
        filled = profile.apply_region_defaults()
        if filled:
            session.messages.append({
                "role": "assistant",
                "text": f"Using typical values for {profile.region}: filled {', '.join(filled)}.",
                "recommendations": [],
            })

    glossary_field = detect_glossary_question(req.message)
    if glossary_field and not updates:
        session.messages.append({"role": "assistant", "text": GLOSSARY[glossary_field], "recommendations": []})

    escape_hatch = wants_escape_hatch(req.message)
    if escape_hatch:
        if profile.region:
            filled = profile.apply_region_defaults()
            if filled:
                session.messages.append({
                    "role": "assistant",
                    "text": f"Using typical values for {profile.region}: filled {', '.join(filled)}.",
                    "recommendations": [],
                })
        else:
            session.pending_escape_hatch = True
            zones = ", ".join(REGION_DEFAULTS)
            session.messages.append({
                "role": "assistant",
                "text": f"To fall back on typical values I'd need at least a region — which one is this land in? ({zones})",
                "recommendations": [],
            })
            return {"session_id": sid, **_serialize(session)}

    question = next_question(profile, INTERVENTIONS)
    if question:
        _, question_text = question
        if not updates and not glossary_field and not escape_hatch:
            question_text = "I didn't catch a usable value in that — " + question_text[0].lower() + question_text[1:]
        session.messages.append({"role": "assistant", "text": question_text, "recommendations": []})
        return {"session_id": sid, **_serialize(session)}

    candidates = filter_candidates(profile, INTERVENTIONS)
    candidates = [c for c in candidates if c["id"] not in session.rejected]
    ranked = rank_candidates(profile, candidates)
    recommendations = build_recommendations(ranked)

    intro = maybe_llm_intro(profile, recommendations)
    session.messages.append({
        "role": "assistant",
        "text": intro,
        "recommendations": [r.model_dump() for r in recommendations],
    })
    return {"session_id": sid, **_serialize(session)}


@app.post("/api/reset")
def reset(req: ResetRequest):
    sid = req.session_id or str(uuid.uuid4())
    SESSIONS[sid] = Session()
    return {"session_id": sid, **_serialize(SESSIONS[sid])}
