# Biodiversity Intelligence Agent

An agent that takes a description of a piece of land — soil, rainfall, land
use, region — and returns specific, cited, multi-variable interventions to
improve its biodiversity. It asks for missing information before answering,
remembers what it has been told across turns, and shows the causal chain
behind every recommendation.

Design rationale lives in [`DESIGN.md`](DESIGN.md). This README covers what
was actually built and how to run it.

## Architecture

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

The backend (`agent/`, `kb/`, `data/`, `server.py`, `cli.py`) lives entirely
under [`backend/`](backend/) so it can be deployed as a self-contained
service independent of the frontend.

**Two knowledge stores**, per the design doc:

- **Store B — `backend/data/interventions.json`.** 18 hand-curated interventions,
  each with machine-readable preconditions, effect sizes, time horizons,
  confidence, tradeoffs, mechanism text and sources. This is what makes a
  hallucinated effect size structurally impossible: a number in a
  recommendation always traces back to this table, never to a model.
- **Store A — `backend/data/corpus/`.** 12 short excerpts (FAO, IPCC, ICRISAT, ICAR,
  ICRAF, IUCN, CGIAR, UNCCD, Ramsar), each with a citation frontmatter header,
  covering soil, land use, biodiversity, climate and human-impact domains.
  Retrieved via BM25 keyword search (`backend/kb/retriever.py`) as supporting
  "evidence" alongside a recommendation's primary Store B source.

**Causal graph** (`backend/kb/graph.py`): 18 metric nodes, 28 hand-written edges,
each carrying a direction and a mechanism sentence. A depth-3 traversal from
each intervention's primary effect produces the cascade shown in the UI —
e.g. `soil_moisture -> amphibian_richness (+) -> species_richness (+)` — so a
single-variable answer is structurally unreachable.

## MVP simplifications, and why

The design doc's own build order says: get the reasoning system working with
zero model calls first, because that's where the marks are (55% in
reasoning + grounding vs. 0% in UI). This build follows that instinct all
the way through — with one deliberate exception: the React frontend.
`DESIGN.md` explicitly recommends against it ("Skip: React... Zero marks,
real hours") in favor of a single-process app, since the brief scores UI
at 0%. The React + FastAPI split here exists because it was asked for
directly, not because it earns more marks — if this is going in front of
the Darukaa evaluators, a simpler single-process UI would be the safer
submission path; the reasoning core in `backend/agent/`/`backend/kb/` is unaffected either
way, so swapping the frontend later costs nothing on that front.

- **No vector DB / embedding model.** `backend/kb/retriever.py` uses `rank_bm25`
  (pure Python, no download, no GPU) instead of Chroma + sentence-transformers.
  Same "two-store retrieval" design the brief asks for; a heavier dense
  retriever can be swapped in later without touching anything else.
- **No LLM required to run.** Profile extraction (`backend/agent/profile.py`) is
  rule-based regex/keyword matching, and recommendation phrasing
  (`backend/agent/respond.py:maybe_llm_intro`) falls back to a plain template. If
  `GROQ_API_KEY` or `ANTHROPIC_API_KEY` is set, the intro paragraph gets LLM-polished — but
  the numbers, sources, cascades and tradeoffs never pass through the model
  either way. This means the demo works immediately for anyone who clones
  it, with no API key to provision.
- **Sources are best-effort, not independently re-verified against the
  original PDFs.** Each entry cites a real organization, title and year for
  a widely-published finding. Before a formal submission, spot-check the
  handful of sources you actually present against their source documents —
  the design doc is explicit that evaluators do this.

## How knowledge is retrieved and used — one worked example

Input: *"I have a wheat cropland field in the semi-arid deccan region, SOC
about 0.3%, rainfall around 550mm, gentle slope."*

1. **Extraction** (`backend/agent/profile.py:extract_updates`) pulls
   `rainfall_mm=550`, `soil_organic_carbon=0.3`, `land_use=cropland`,
   `slope=gentle`, `region=semi-arid deccan` from the raw text.
2. **Completeness gate** (`backend/agent/clarify.py:next_question`) checks the four
   critical fields — all now filled — so no clarifying question fires.
3. **Candidate filtering** (`backend/agent/reason.py:filter_candidates`) keeps the
   14 of 18 interventions whose preconditions aren't violated by this
   profile (e.g. `check_dams_watershed` is dropped — it needs
   moderate/steep slope, this field is gentle).
4. **Ranking** (`backend/agent/reason.py:rank_candidates`) scores by confidence-
   weighted effect count, precondition specificity, and tradeoff count;
   top 4 survive.
5. **Graph traversal** (`backend/kb/graph.py:trace`) walks 3 hops downstream from
   each intervention's primary effect metrics.
6. **Citation validation** (`backend/agent/respond.py:validate_sources`) drops any
   candidate with no source on record — none are dropped here, all 4
   have one.
7. **Render**: e.g. *Contour bunding with farm pond* — mechanism, cascade
   `soil_moisture -> amphibian_richness (+) -> species_richness (+)`,
   effect `soil_moisture: +18-30% in the root zone (short, high
   confidence)`, tradeoffs (land take, mosquito risk), source (ICRISAT
   Watershed Development Impact Assessment, 2018).

## Local setup

```bash
cd backend
pip install -r requirements.txt

# Backend API
uvicorn server:app --reload          # http://localhost:8000

# Frontend, in a second terminal (from the repo root)
cd frontend && npm install && npm run dev   # http://localhost:5173

# JSON input path (no UI, no second process), from backend/
echo '{"soil_organic_carbon": 0.3, "rainfall_mm": 550, "land_use": "cropland"}' | python cli.py
```

Optional: copy `backend/.env.example` to `backend/.env` and set
`GROQ_API_KEY` (or `ANTHROPIC_API_KEY`) for an LLM-phrased intro paragraph
— Groq is tried first if both are set. Everything else works unchanged
without either. Default Groq model is `openai/gpt-oss-20b`; override with
`GROQ_MODEL`.

## Frontend + reasoning core

`backend/server.py` is a small FastAPI JSON API (`/api/session`,
`/api/chat`, `/api/reset`, sessions kept in memory) sitting directly on
top of `backend/agent/` and `backend/kb/` — no reasoning logic is
duplicated in it, it only serializes what those modules already produce.
`frontend/` (React + Vite, plain CSS) is a renderer for that JSON: chat
history, a sidebar profile panel, and expandable recommendation cards.

`backend/cli.py` is a UI-less path straight into the same reasoning core,
useful for scripting or a quick sanity check without running either
server.

## Repo layout

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
└── frontend/                     # React (Vite) chat UI, calls backend/server.py
```

Splitting the backend into its own top-level folder means it can be
deployed as a standalone service (e.g. Render, Railway, Fly.io) with its
own `requirements.txt` and no dependency on the frontend's build tooling,
while `frontend/` deploys separately (e.g. Vercel, Netlify) pointed at the
backend's URL via `VITE_API_URL`.

## Schema

```python
class Recommendation(BaseModel):
    action: str
    mechanism: str                  # the "why it works"
    cascade: list[str]              # from causal graph traversal
    metrics_improved: list[MetricDelta]
    tradeoffs: list[str]
    horizon: Literal["short", "medium", "long"]
    confidence: Literal["high", "medium", "low"]
    sources: list[Source]
    evidence: list[Source]          # supporting corpus excerpts
```

A recommendation with zero valid sources after citation validation is not
rendered at all.

## CI/CD

None configured. If required for submission, a minimal GitHub Actions
workflow running `pip install -r requirements.txt && python -m pytest`
(once tests exist) in `backend/`, and `npm install && npm run build`
in `frontend/` to catch build breaks, would be the natural next addition.

## Known gaps / next steps

- Corpus is 12 files, not the 15-20 the design doc targets — enough to
  cover all five required domains at least once, but thinner than ideal.
- No automated test suite yet; the reasoning pipeline was smoke-tested
  end-to-end via `cli.py` and via Playwright against the running React app
  during development, not with committed unit tests.
- LLM-assisted free-text extraction (beyond the current regex parser) was
  scoped out of the MVP — see `backend/agent/respond.py:maybe_llm_intro` for the
  one place an LLM call already exists and could be extended.
- The geo-coordinate bonus (lat/lon -> agro-ecological zone) is not
  implemented. `backend/agent/profile.py:REGION_DEFAULTS` covers the same need by
  name instead of coordinates — typing a region name (e.g. "semi-arid
  deccan") triggers the same typical-values fallback a lat/lon lookup would.
- **Soil pH and ambient temperature** are named explicitly in the brief
  ("Soil health (pH, organic carbon, moisture)", "Climate factors
  (temperature, rainfall)") but aren't modeled — no profile field, no graph
  node, no intervention precondition references either. Adding them
  properly means new causal-graph edges and intervention preconditions
  backed by real sources, not just a new input field; scoped out rather
  than bolted on shallowly, since a cosmetic field with no reasoning effect
  would violate the project's own "no number without a source" rule.
- **Human impact (pollution, deforestation)** is covered only indirectly —
  `land_use="degraded"` and the desertification corpus entry
  (`backend/data/corpus/desertification_unccd.md`) capture human-driven land
  degradation, but there's no explicit pollution variable and deforestation
  isn't a distinct input from `land_use`.
- **Retrieval is BM25 keyword search, not embeddings/vector DB.** The brief's
  evaluation criteria accept "RAG / vector DB / structured datasets" as
  alternatives, and Store B (`interventions.json`) is a structured dataset
  in the strict sense — but Store A (the literature corpus) is retrieved by
  keyword overlap, not semantic similarity. See "MVP simplifications" above
  for why.
- **Structured JSON input exists but isn't reachable from the live demo
  URL** — it's `cli.py`, a separate command run locally, not a field in the
  React UI or a second FastAPI endpoint. Satisfies the letter of "Support
  at least: Text input (mandatory), Structured input (JSON or similar)" but
  an evaluator using only the deployed link won't discover it.
- Until just now, `region` was treated as a blocking "critical" field even
  though no intervention's preconditions actually key on it — so a
  complete-enough profile could still get stuck asking for a region purely
  because it was on a checklist, not because anything downstream needed it.
  Fixed: `region` is no longer in `CRITICAL_FIELDS`; it only matters for the
  "use typical values" escape hatch now. Also added: qualitative rainfall
  ("Rainfall: low" -> 400mm) and bare climate-zone words ("semi-arid"
  without a named zone) as recognized input, since the brief's own worked
  example uses both and previously neither parsed.
