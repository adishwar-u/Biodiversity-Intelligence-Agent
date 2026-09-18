# Biodiversity Intelligence Agent — Documentation

An agent that takes a description of a piece of land (soil, rainfall, land
use, region) and returns specific, cited, multi-variable interventions to
improve its biodiversity. It asks for missing information before answering,
remembers what it has been told across turns, and shows the causal chain
behind every recommendation.

This document is a full technical reference for the project: what it does,
how it is built, every module's contract, the data formats, the APIs, and
how to run and extend it. For the original design rationale and scoring
tradeoffs, see [`DESIGN.md`](DESIGN.md). For a shorter, evaluator-facing
overview, see [`README.md`](README.md).

---

## Table of contents

1. [What the system does](#1-what-the-system-does)
2. [High-level architecture](#2-high-level-architecture)
3. [Knowledge stores](#3-knowledge-stores)
4. [Causal graph](#4-causal-graph)
5. [Request pipeline, step by step](#5-request-pipeline-step-by-step)
6. [Module reference](#6-module-reference)
7. [Output schema](#7-output-schema)
8. [Backend API (`server.py`)](#8-backend-api-serverpy)
9. [Frontend (`frontend/`)](#9-frontend-frontend)
10. [CLI (`cli.py`)](#10-cli-clipy)
11. [Local setup](#11-local-setup)
12. [Configuration / environment variables](#12-configuration--environment-variables)
13. [Repo layout](#13-repo-layout)
14. [Design decisions and MVP simplifications](#14-design-decisions-and-mvp-simplifications)
15. [Known gaps / next steps](#15-known-gaps--next-steps)
16. [Worked example](#16-worked-example)

---

## 1. What the system does

Given a free-text description or structured JSON describing a plot of land,
the agent:

1. Extracts what it can (soil organic carbon, rainfall, land use, slope,
   region) using deterministic rule-based parsing — no LLM required.
2. Asks exactly one clarifying question at a time for whatever critical
   field is still missing, choosing the question that best splits the
   surviving set of candidate interventions (information-gain style), not
   just the first blank field in a fixed order.
3. Filters a curated table of 18 interventions down to the ones whose
   preconditions are compatible with what's known about the land.
4. Ranks the survivors by confidence-weighted effect count, precondition
   specificity, and tradeoff count, and keeps the top 4.
5. Traces each surviving intervention's effects through a hand-built causal
   graph (depth-3) to produce a multi-variable cascade, e.g.
   `soil_moisture -> amphibian_richness (+) -> species_richness (+)`.
6. Validates that every recommendation has at least one real citation;
   drops any that doesn't.
7. Renders the result as a structured `Recommendation` object (action, why
   it works, cascade, metrics improved, tradeoffs, horizon, confidence,
   sources, supporting literature) via the React frontend, the FastAPI
   JSON API, or the CLI.

Because every effect size and citation traces back to a fixed table
(`backend/data/interventions.json`), a hallucinated number is structurally
impossible — the reasoning pipeline runs with **zero model calls** by
default. An LLM (Groq or Anthropic) is used *only* to phrase the optional
intro paragraph, never to generate facts.

---

## 2. High-level architecture

```
User message (chat or JSON)
        |
        v
[1] Rule-based extractor   backend/agent/profile.py   -> fills EnvironmentalProfile
        |
[2] Completeness gate      backend/agent/clarify.py   -> missing critical field? ask ONE
        |                                                 information-gain-ranked question
        v
[3] Candidate filter       backend/agent/reason.py    -> Store B: interventions.json filtered
        |                                                 by matching preconditions
[4] Graph reasoner         backend/kb/graph.py        -> depth-3 traversal of the causal
        |                                                 graph from each primary effect
[5] Ranker                 backend/agent/reason.py    -> score by confidence, precondition
        |                                                 specificity, tradeoff count
[6] Citation validator     backend/agent/respond.py   -> drop any intervention with no
        |                                                 valid source; never render it
        v
Structured Recommendation (Pydantic) -> rendered in backend/server.py+frontend/ / backend/cli.py
```

Three entry points share the exact same reasoning core (`backend/agent/` + `backend/kb/`):

- `backend/server.py` — a FastAPI JSON API consumed by the React frontend.
- `frontend/` — a React + Vite chat UI that renders that JSON.
- `backend/cli.py` — a stdin/stdout JSON path with no server involved.

None of the three entry points duplicate reasoning logic; they only
orchestrate calls into `backend/agent/` and `backend/kb/` and serialize the result for
their respective surface.

---

## 3. Knowledge stores

The design deliberately splits knowledge into two stores, because pure RAG
produces prose that *sounds* scientific but doesn't reliably produce
defensible numbers.

### Store B — `backend/data/interventions.json` (structured, authoritative)

18 hand-curated intervention rows. Each row is a JSON object with:

| Field | Type | Purpose |
|---|---|---|
| `id` | string | stable identifier |
| `name` | string | human-readable action name (`Recommendation.action`) |
| `preconditions` | object | field → condition; see [filtering rules](#filter_candidates) |
| `effects` | array of `{metric, delta, horizon, confidence}` | what improves, by how much, over what time horizon, at what confidence |
| `tradeoffs` | array of strings | always populated — the thing that separates a scientist's answer from a brochure's |
| `mechanism` | string | one or two sentences on *why* the intervention works |
| `sources` | array of `{title, org, year, locator}` | citation(s); a recommendation with none of these is never rendered |

This table is what makes a hallucinated effect size structurally
impossible: every number in a rendered recommendation traces back to this
JSON, never to a model. Filtering and ranking against it are plain Python
(`backend/agent/reason.py`), not semantic retrieval.

The 18 interventions currently in the table:

```
farm_pond_bunding                 legume_cover_crop
agroforestry_boundary_planting    hedgerow_field_margins
no_till_conservation_agriculture  rotational_grazing
vermicompost_organic_amendment    mulching_residue_retention
check_dams_watershed              native_tree_afforestation
intercropping_diversification     wetland_restoration
beetle_banks_pest_refugia         silvopasture
drip_irrigation_water_efficiency  windbreak_shelterbelt
biochar_soil_amendment            riparian_buffer_restoration
```

### Store A — `backend/data/corpus/` (literature excerpts, supporting evidence)

12 short markdown files, each with a YAML frontmatter citation header
(`title`, `org`, `year`, `topic`) followed by a plain-text excerpt. Example
(`backend/data/corpus/biochar_soil_carbon.md`):

```markdown
---
title: "Biochar for Sustainable Soil Management"
org: CGIAR
year: 2019
topic: soil
---

Biochar — organic material pyrolysed at high temperature in low oxygen —
behaves differently from fresh compost or residue once in soil...
```

Sources represented: FAO, IPCC, ICRISAT, ICAR, ICRAF, IUCN, CGIAR, UNCCD,
Ramsar — covering soil, land use, biodiversity, climate and human-impact
domains, per the brief's five required domains.

Retrieved via BM25 keyword search (`backend/kb/retriever.py`, `rank_bm25`) and
attached to a recommendation as `evidence` — supporting context alongside
(never instead of) the intervention's primary Store B `sources`.

---

## 4. Causal graph

`backend/kb/graph.py` defines a hand-written directed graph over 18 metric nodes
with 28 edges. Every edge is a 4-tuple:

```python
(source_metric, target_metric, sign, mechanism_sentence)
```

e.g.

```python
("soil_organic_carbon", "water_holding_capacity", "+",
 "Each 1% increase in SOC raises available water capacity roughly 1.5-2% by volume."),
```

`trace(metric, depth=3)` performs a depth-limited DFS from a metric,
returning a nested structure of `{link, sign, mechanism, downstream}`
dicts. `flatten_chain(nodes)` turns that into flat, printable path strings
like:

```
water_holding_capacity (+) -> drought_resilience (+) -> flowering_duration (+)
```

Because every recommendation's cascade is built by walking this graph from
its *primary* effect metric, a single-variable answer ("low SOC, so add
compost") is structurally unreachable — the chain is already
multi-variable before any rendering happens. This is the mechanism behind
the "depth of reasoning" scoring criterion.

The graph nodes span soil (`soil_organic_carbon`, `soil_erosion`,
`soil_temperature`), water (`water_holding_capacity`, `soil_moisture`,
`groundwater_recharge`, `drought_resilience`), vegetation
(`canopy_cover`, `vegetation_structural_diversity`, `field_margin_habitat`,
`habitat_fragmentation`), and biodiversity/yield outcomes
(`pollinator_abundance`, `species_richness`, `bird_diversity`,
`amphibian_richness`, `pest_natural_enemies`, `crop_yield_stability`,
`flowering_duration`).

---

## 5. Request pipeline, step by step

Both `backend/server.py`'s `/api/chat` and `backend/cli.py`'s `run()` follow the same
sequence (the server additionally persists an `EnvironmentalProfile` per
session, and layers in glossary/escape-hatch handling described below):

1. **Extraction** — `agent.profile.extract_updates(text)` pulls whichever
   of `rainfall_mm`, `soil_organic_carbon`, `land_use`, `slope`, `region`
   it can find via regex/keyword matching, and the caller applies the
   updates onto the session's `EnvironmentalProfile`.
2. **Completeness gate** — `agent.clarify.next_question(profile,
   interventions)` checks whether a critical field is still missing. If
   so, it returns one question (see [§6.2](#agentclarifypy)); the pipeline
   stops there for this turn and no recommendations are computed.
3. **Candidate filtering** — `agent.reason.filter_candidates(profile,
   interventions)` keeps every intervention whose preconditions are not
   *violated* by known profile values (unknown fields never exclude a
   candidate — that's what makes them worth asking about).
4. **Ranking** — `agent.reason.rank_candidates(profile, candidates,
   top_n=4)` scores and keeps the top 4 (see [§6.3](#agentreasonpy) for
   the scoring formula).
5. **Graph traversal** — `agent.reason.cascade_for(interv)` walks
   `kb.graph.trace` from each of the intervention's effect metrics and
   flattens the paths.
6. **Citation validation** — `agent.respond.build_recommendation(interv)`
   drops the intervention if it has zero real sources or zero effects;
   otherwise assembles a full `Recommendation`, including a BM25 lookup
   into Store A for `evidence`.
7. **Render** — the intro paragraph is generated by
   `agent.respond.maybe_llm_intro` (LLM-phrased if an API key is
   configured, otherwise a plain template), and each caller (`backend/server.py`,
   `backend/cli.py`) serializes the `Recommendation` list for its surface.

---

## 6. Module reference

### `backend/agent/profile.py`

Defines `EnvironmentalProfile` (a Pydantic model) and all rule-based
free-text extraction. No LLM dependency.

- **Fields**: `soil_organic_carbon` (float, %), `rainfall_mm` (float),
  `land_use` (`Literal["cropland", "degraded", "pasture", "grassland",
  "forest"]`), `slope` (`Literal["flat", "gentle", "moderate", "steep"]`),
  `region` (free string), `notes` (list of strings).
- **`CRITICAL_FIELDS`** = `["soil_organic_carbon", "rainfall_mm",
  "land_use"]`. `region` is deliberately excluded: no intervention's
  preconditions key on it, so it can't affect filtering — it only unlocks
  the "typical values" escape hatch.
- **`missing_critical_fields()`** — returns whichever of `CRITICAL_FIELDS`
  is still `None`.
- **`REGION_DEFAULTS`** — a dict of 8 named Indian agro-climatic zones
  (`semi-arid deccan`, `indo-gangetic plains`, `arid rajasthan`, `western
  ghats`, `central highlands`, `coastal andhra`, `north-east hills`,
  `kutch`), each mapping to typical `rainfall_mm` / `soil_organic_carbon` /
  `land_use` values.
- **`apply_region_defaults()`** — fills any still-missing field from the
  matched region's typical values; returns the list of fields filled.
  Requires the region to be a case-insensitive exact match against
  `REGION_DEFAULTS` keys.
- **`extract_updates(text)`** — the extraction entry point. Recognizes:
  - Rainfall as a bare number + `mm` (highest priority), or a qualitative
    word near "rainfall" (`low` → 400mm, `moderate`/`medium` → 750mm,
    `high`/`heavy` → 1400mm, `very high` → 2000mm, `very low`/`scanty`/
    `scarce` → 250mm).
  - SOC as `N% SOC` / `SOC N%` / a bare `N%` near organic-carbon wording.
  - Land use, slope, and region via keyword lists (`_LAND_USE_KEYWORDS`,
    `_SLOPE_KEYWORDS`, named region keys, then generic climate words like
    "semi-arid", "arid", "coastal" as a region fallback).
- **`wants_escape_hatch(text)`** — true if the message contains a phrase
  like "not sure", "use typical values", "your call", etc.
- **`detect_glossary_question(text)`** / **`GLOSSARY`** — recognizes a
  genuine question about a field ("what is SOC?") via `_QUESTION_STARTERS`
  and per-field keyword lists, and returns a canned plain-English
  explanation instead of silently re-asking the same clarifying question.

### `backend/agent/clarify.py`

- **`QUESTION_TEMPLATES`** — one question string per critical field, each
  ending with the escape-hatch offer ("If you're not sure, I can work from
  typical values for your region instead.").
- **`next_question(profile, interventions)`** — for each still-missing
  critical field, computes `score = min(gated, total - gated)` where
  `gated` is the count of interventions whose preconditions reference that
  field. This is an information-gain proxy: the field that most evenly
  splits the candidate set is asked first, because that's the question
  most likely to actually change which interventions survive filtering.
  Falls back to the first remaining missing field if nothing scored (can
  happen if only `region` is missing, which gates nothing directly).
  Returns `(field_name, question_text)` or `None` if the profile is
  complete.

### `backend/agent/reason.py`

No LLM call happens in this module.

- **`load_interventions()`** — reads and parses `backend/data/interventions.json`.
- **`_satisfies(value, condition)`** — a condition is either a `[low,
  high]` numeric range, a list of allowed discrete values, or an exact
  match.
- <a name="filter_candidates"></a>**`filter_candidates(profile,
  interventions)`** — keeps an intervention unless a precondition the
  profile *has data for* is violated. A precondition field the profile
  hasn't answered yet never excludes a candidate.
- <a name="agentreasonpy"></a>**`_score(interv, profile)`** —
  `effect_score` (sum of confidence weights `{high: 3, medium: 2, low: 1}`
  across all effects) `+ specificity_bonus` (1 point per precondition
  field the profile actually has a value for) `- tradeoff_penalty` (`0.3 *
  len(tradeoffs)`).
- **`rank_candidates(profile, candidates, top_n=4)`** — sorts by `_score`
  descending, returns the top 4.
- **`cascade_for(interv, depth=3)`** — for each of the intervention's
  effect metrics, calls `kb.graph.trace` then `kb.graph.flatten_chain`,
  returning `{metric: [path_strings]}`.
- **`get_recommendations(profile, top_n=4)`** — convenience wrapper
  chaining `load_interventions` → `filter_candidates` → `rank_candidates`.

### `backend/agent/respond.py`

Defines the output schema (`Source`, `MetricDelta`, `Recommendation`) and
the citation validator.

- **`validate_sources(interv)`** — the sole choke point through which a
  source can reach a rendered recommendation: only sources present on the
  curated JSON row with both a `title` and `org` pass through. Nothing
  downstream can add a source that wasn't already here.
- **`build_recommendation(interv)`** — returns `None` (i.e. does not
  render) if there are zero valid sources or zero effects. Otherwise:
  builds `metrics_improved` from `effects`; builds `cascade` from
  `cascade_for` (capped at 2 paths per metric so one intervention can't
  dump the whole graph); computes overall `horizon`/`confidence` as the
  *most urgent/most confident* single effect's horizon/confidence (i.e.
  `min` by `_HORIZON_ORDER` / `_CONFIDENCE_ORDER`); queries the BM25
  retriever for 2 supporting `evidence` documents using the intervention
  name + its effect metric names as the query.
- **`build_recommendations(interventions)`** — maps `build_recommendation`
  over a list, dropping any `None`.
- **`maybe_llm_intro(profile, recommendations)`** — if `GROQ_API_KEY` or
  `ANTHROPIC_API_KEY` is set, asks the model for a 2–3 sentence intro
  paragraph (Groq tried first, via `_groq_intro`, falling back to
  `_anthropic_intro`); the prompt explicitly instructs the model not to
  invent numbers or sources. Any exception or missing key falls back to
  `_template_intro`, a deterministic string. **No number, source, or
  cascade ever passes through the LLM** — only the framing prose does.
  - Groq: model defaults to `GROQ_MODEL` env var or `openai/gpt-oss-20b`,
    `max_tokens=500` (gpt-oss spends part of its budget on hidden
    reasoning tokens).
  - Anthropic: model `claude-sonnet-5`, `max_tokens=200`.

### `backend/kb/graph.py`

See [§4](#4-causal-graph). Also exposes `all_metrics()` (sorted list of
every node name that appears as a source or destination) and has a
`__main__` block that prints the 3-hop cascade from
`soil_organic_carbon` for a quick manual sanity check
(`python -m kb.graph`).

### `backend/kb/retriever.py`

- **`Document`** dataclass: `id`, `title`, `org`, `year`, `topic`, `body`.
- **`_parse_frontmatter(raw)`** — splits a markdown file's leading
  `---`-delimited YAML-ish block from its body using simple `key: value`
  line parsing (not a full YAML parser).
- **`Retriever.__init__`** — loads every `*.md` file under
  `backend/data/corpus/`, tokenizes `f"{title} {body}"` with a lowercase
  `[a-z0-9]+` regex, and builds a `BM25Okapi` index over the corpus.
- **`Retriever.search(query, top_k=3)`** — returns the top-`k` documents
  with a BM25 score `> 0`; returns `[]` if the corpus is empty or the
  query is blank.
- **`get_retriever()`** — process-wide singleton so the BM25 index is
  built once, not per-request.

---

## 7. Output schema

```python
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
    mechanism: str                  # the "why it works"
    cascade: list[str]              # from causal graph traversal
    metrics_improved: list[MetricDelta]
    tradeoffs: list[str]
    horizon: Literal["short", "medium", "long"]
    confidence: Literal["high", "medium", "low"]
    sources: list[Source]           # curated Store B citations
    evidence: list[Source]          # supporting Store A corpus excerpts
```

Pydantic enforces that the four mandatory elements from the brief — what
to do, why it works, which metric improves, which source backs it — can
never be omitted from a rendered recommendation. A candidate that survives
filtering and ranking but has zero valid sources after citation validation
is not rendered at all (`build_recommendation` returns `None`).

---

## 8. Backend API (`server.py`)

Lives at `backend/server.py`. A thin FastAPI wrapper around `backend/agent/` and `backend/kb/` — it contains no
reasoning logic of its own, only session bookkeeping and JSON
serialization. Sessions are kept **in memory** (a process restart clears
them; there is no cross-process persistence, which is acceptable for a
local MVP demo).

CORS is enabled for `http://localhost:5173` and `http://127.0.0.1:5173`
(the Vite dev server origins).

### `GET /api/session?session_id=<optional>`

Returns (creating a new session if `session_id` is absent or unknown):

```json
{
  "session_id": "...",
  "profile": {
    "region": null, "rainfall_mm": null, "soil_organic_carbon": null,
    "land_use": null, "slope": null,
    "summary_lines": [], "missing_critical_fields": [...]
  },
  "messages": [ { "role": "assistant", "text": "...", "recommendations": [] } ]
}
```

### `POST /api/chat`

Body: `{"session_id": "...", "message": "..."}`.

Behavior, in order:

1. Appends the user's message to session history.
2. Runs `extract_updates` and applies any updates onto the profile.
3. If a region-only escape hatch was previously pending
   (`pending_escape_hatch`) and a region is now known, applies
   `apply_region_defaults()` and announces which fields got filled.
4. If the message is a glossary question (`detect_glossary_question`) and
   contained no other extractable updates, answers from `GLOSSARY` instead
   of re-asking a clarifying question.
5. If the message invokes the escape hatch (`wants_escape_hatch`): applies
   region defaults immediately if a region is already known; otherwise
   sets `pending_escape_hatch = True` and asks specifically for a region,
   listing the known `REGION_DEFAULTS` zone names, and returns early.
6. Otherwise, calls `next_question`. If a critical field is still missing,
   asks it (prefixing "I didn't catch a usable value in that — " if the
   message produced no updates/glossary hit/escape hatch) and returns
   early — no recommendations are computed this turn.
7. Otherwise: filters candidates, excludes any the user has previously
   rejected (`session.rejected`, currently populated but not yet exposed
   via an API for rejecting — see [§15](#15-known-gaps--next-steps)),
   ranks, builds recommendations, generates the intro, and appends an
   assistant message carrying both the intro text and the serialized
   `Recommendation` list.

Response shape matches `GET /api/session`'s, i.e. `{"session_id", "profile", "messages"}`.

### `POST /api/reset`

Body: `{"session_id": "..."}` (optional). Replaces the session with a
fresh `Session()` (new or reused ID) and returns the freshly-serialized
state, same shape as the other two endpoints.

---

## 9. Frontend (`frontend/`)

React 19 + Vite 8, plain CSS (no component framework, no CSS-in-JS). Talks
to the backend only through `frontend/src/api.js`, which reads the API
base URL from `VITE_API_URL` (default `http://localhost:8000`).

- **`App.jsx`** — top-level layout: a sidebar showing the inferred
  `EnvironmentalProfile` (`summary_lines`, plus any
  `missing_critical_fields`) and a reset button; a main chat panel
  rendering message history plus `RecommendationCard`s inline under
  assistant messages that carry them. Session ID is persisted in
  `localStorage` (`darukaa_session_id`) so a page reload resumes the same
  conversation.
- **`RecommendationCard.jsx`** — an expandable `<details>` card per
  recommendation: title + horizon/confidence badges, mechanism ("why it
  works"), up to 3 cascade lines (rendered with `→` arrows), metrics
  improved, tradeoffs, curated sources, and a one-line "Supporting
  literature" summary of `evidence` documents.
- **`api.js`** — three thin `fetch` wrappers: `getSession`, `sendMessage`,
  `resetSession`; each throws on a non-OK response.

No routing, no state management library, no custom CSS framework — per
the design doc's explicit instruction to keep UI effort minimal, since it
scores 0% in the underlying evaluation brief.

---

## 10. CLI (`cli.py`)

Lives at `backend/cli.py`. A UI-less path straight into the same reasoning
core — useful for scripting or a quick sanity check without running any
server.

```bash
cd backend
echo '{"soil_organic_carbon": 0.3, "rainfall_mm": 550, "land_use": "cropland"}' | python cli.py
```

Reads a single JSON object from stdin, constructs an `EnvironmentalProfile`
from it directly (no free-text extraction — the profile fields must
already be named correctly), and:

- If a critical field is missing, prints which field triggered a
  clarifying question and its text, then continues anyway (unset fields
  simply aren't used to filter — this is a single-shot script, not a
  multi-turn conversation, so it can't actually wait for an answer).
- Filters, ranks, builds recommendations, prints the intro, then for each
  recommendation prints action, mechanism, horizon/confidence, up to 3
  cascade lines, metrics improved, tradeoffs, and sources as plain text.

Exits with an error message (and status 1) if stdin is empty.

---

## 11. Local setup

```bash
cd backend
pip install -r requirements.txt

# Backend API (from backend/)
uvicorn server:app --reload          # http://localhost:8000

# Frontend, in a second terminal (from the repo root)
cd frontend && npm install && npm run dev   # http://localhost:5173

# JSON input path (no UI, no second process), from backend/
echo '{"soil_organic_carbon": 0.3, "rainfall_mm": 550, "land_use": "cropland"}' | python cli.py
```

Optional: copy `backend/.env.example` to `backend/.env` and set `GROQ_API_KEY` (or
`ANTHROPIC_API_KEY`) for an LLM-phrased intro paragraph. Both `backend/server.py`
and `backend/cli.py` call `load_dotenv()` on startup. Everything else — the
recommendations, effect sizes, cascades, tradeoffs, sources — works
identically with or without either key.

Ready-to-paste example inputs for manual testing live in
[`ask_questions.md`](ask_questions.md), including one-shot complete
profiles and multi-turn flows that exercise the clarifying-question and
escape-hatch logic.

### Python dependencies (`backend/requirements.txt`)

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.6
rank_bm25>=0.2.2
groq>=0.11
anthropic>=0.40
python-dotenv>=1.0
```

### Frontend dependencies (`frontend/package.json`)

```
react ^19.2.8, react-dom ^19.2.8
@vitejs/plugin-react ^6.1.1, vite ^8.3.0, oxlint ^1.81.0 (dev)
```

Scripts: `npm run dev` (Vite dev server), `npm run build` (production
build), `npm run lint` (oxlint), `npm run preview`.

---

## 12. Configuration / environment variables

| Variable | Required? | Effect |
|---|---|---|
| `GROQ_API_KEY` | No | If set, `maybe_llm_intro` asks Groq for the intro paragraph (tried first if both keys are set). |
| `GROQ_MODEL` | No | Overrides the Groq model, default `openai/gpt-oss-20b`. |
| `ANTHROPIC_API_KEY` | No | If set (and Groq isn't, or Groq fails), asks Anthropic (`claude-sonnet-5`) for the intro paragraph instead. |
| `VITE_API_URL` (`frontend/.env`) | No | Overrides the backend base URL the frontend calls, default `http://localhost:8000`. |

None of these affect which interventions are surfaced, their effect sizes,
their cascades, or their citations — those are always sourced from
`backend/data/interventions.json` and `backend/kb/graph.py`, never from a model.

---

## 13. Repo layout

```
darukaa-biodiversity-agent/
├── backend/
│   ├── data/
│   │   ├── interventions.json    # 18 curated rows — Store B
│   │   └── corpus/               # 12 cited source excerpts — Store A
│   ├── kb/
│   │   ├── graph.py              # metric causal graph + traversal
│   │   └── retriever.py          # BM25 search over the corpus
│   ├── agent/
│   │   ├── profile.py            # EnvironmentalProfile + rule-based extraction
│   │   ├── clarify.py            # information-gain clarifying question picker
│   │   ├── reason.py             # precondition filtering + ranking + cascades
│   │   └── respond.py            # Pydantic output schema + citation validator
│   ├── server.py                 # FastAPI JSON API for the React frontend
│   ├── cli.py                    # JSON stdin -> stdout path
│   ├── requirements.txt
│   ├── .env.example
│   └── .env                      # not committed — API keys, optional
├── frontend/                     # React (Vite) chat UI, calls backend/server.py
├── ask_questions.md              # ready-to-paste example chat inputs
├── DESIGN.md                     # original design/scoring rationale
├── README.md                     # evaluator-facing overview
└── DOCUMENT.md                   # this file
```

The backend is a self-contained folder — its own `requirements.txt`, its
own `.env`, no dependency on `frontend/`'s toolchain — so it can be
deployed independently (e.g. as a Render/Railway/Fly.io service) from the
frontend (e.g. Vercel/Netlify), with the frontend's `VITE_API_URL`
pointed at wherever the backend ends up.

---

## 14. Design decisions and MVP simplifications

The design doc's own build order prioritizes the reasoning system (55% of
scoring weight is in reasoning + grounding vs. 0% in UI). This build
follows that instinct throughout, with one deliberate exception — the
React frontend — built because it was directly requested, even though the
design doc recommends a simpler single-process UI instead.

- **No vector DB / embedding model.** `backend/kb/retriever.py` uses `rank_bm25`
  (pure Python, no download, no GPU) instead of Chroma +
  sentence-transformers, satisfying the same "two-store retrieval" shape
  the brief asks for. A heavier dense retriever can be swapped in later
  by replacing only this module.
- **No LLM required to run.** Profile extraction is rule-based
  regex/keyword matching; recommendation phrasing falls back to a plain
  template with no key configured. This means the demo works immediately
  for anyone who clones it, with zero API key provisioning.
- **Sources are best-effort, not independently re-verified against the
  original source PDFs.** Each entry cites a real organization, title, and
  year for a widely-published finding, but a formal submission should
  spot-check the handful of sources actually presented against their
  source documents.

---

## 15. Known gaps / next steps

- Corpus is 12 files, not the 15–20 the design doc targets — enough to
  cover all five required domains at least once, but thinner than ideal.
- No automated test suite yet; the reasoning pipeline was smoke-tested
  end-to-end via `backend/cli.py` and via Playwright against the running React app
  during development, not with committed unit tests.
- LLM-assisted free-text extraction (beyond the current regex parser) was
  scoped out of the MVP — `backend/agent/respond.py:maybe_llm_intro` is the one
  place an LLM call already exists and could be extended.
- The geo-coordinate bonus (lat/lon → agro-ecological zone) is not
  implemented. `backend/agent/profile.py:REGION_DEFAULTS` covers the same need by
  name instead of coordinates.
- **Soil pH and ambient temperature** are named explicitly in the brief
  but aren't modeled — no profile field, no graph node, no intervention
  precondition references either. Scoped out rather than bolted on
  shallowly, since adding them properly requires new causal-graph edges
  and preconditions backed by real sources.
- **Human impact (pollution, deforestation)** is covered only indirectly —
  `land_use="degraded"` and the desertification corpus entry
  (`backend/data/corpus/desertification_unccd.md`) capture human-driven land
  degradation, but there's no explicit pollution variable and
  deforestation isn't distinct from `land_use`.
- **Retrieval is BM25 keyword search, not embeddings/vector DB** for Store
  A (the literature corpus); Store B (`interventions.json`) is itself a
  structured dataset, which the brief's evaluation criteria explicitly
  accept as an alternative.
- **Structured JSON input exists but isn't reachable from the live demo
  URL** — it's `backend/cli.py`, a separate command run locally, not a field in
  the React UI or a second FastAPI endpoint.
- `session.rejected` is tracked in `backend/server.py` but there is currently no
  API surface for a user to actually reject a recommendation and trigger
  re-ranking around it.
- No CI/CD configured. If required, a minimal GitHub Actions workflow
  running `pip install -r requirements.txt && python -m pytest` (once
  tests exist) plus `npm install && npm run build` in `frontend/` would be
  the natural next addition.

---

## 16. Worked example

Input: *"I have a wheat cropland field in the semi-arid deccan region, SOC
about 0.3%, rainfall around 550mm, gentle slope."*

1. **Extraction** (`backend/agent/profile.py:extract_updates`) pulls
   `rainfall_mm=550`, `soil_organic_carbon=0.3`, `land_use="cropland"`,
   `slope="gentle"`, `region="semi-arid deccan"` from the raw text.
2. **Completeness gate** (`backend/agent/clarify.py:next_question`) checks the
   three critical fields — all now filled — so no clarifying question
   fires.
3. **Candidate filtering** (`backend/agent/reason.py:filter_candidates`) keeps 14
   of 18 interventions whose preconditions aren't violated by this
   profile (e.g. `check_dams_watershed` is dropped — it needs
   moderate/steep slope, and this field is gentle).
4. **Ranking** (`backend/agent/reason.py:rank_candidates`) scores by
   confidence-weighted effect count, precondition specificity, and
   tradeoff count; the top 4 survive.
5. **Graph traversal** (`backend/kb/graph.py:trace`) walks 3 hops downstream from
   each surviving intervention's primary effect metrics.
6. **Citation validation** (`backend/agent/respond.py:validate_sources`) drops any
   candidate with no source on record — none are dropped here, all 4 have
   one.
7. **Render**: e.g. *Contour bunding with farm pond* — mechanism, cascade
   `soil_moisture -> amphibian_richness (+) -> species_richness (+)`,
   effect `soil_moisture: +18-30% in the root zone (short, high
   confidence)`, tradeoffs (land take, mosquito risk), source (ICRISAT
   Watershed Development Impact Assessment, 2018).
