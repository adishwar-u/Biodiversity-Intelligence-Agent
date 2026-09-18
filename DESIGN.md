# Biodiversity Intelligence Agent — Design Spec

Interview project for Darukaa.Earth. Working design doc, not a chat log.

---

## 1. What is being built

An AI system that takes a description of a piece of land — soil, rainfall, land use, region — and returns specific, cited, multi-variable interventions to improve biodiversity on it. It asks for missing information before answering, remembers what it has been told across turns, and shows the causal chain behind every recommendation.

The brief's own words: behave like an environmental scientist, not a chatbot.

---

## 2. Scoring, and what it implies

| Criterion | Weight | Where it is earned in this design |
|---|---|---|
| Depth of reasoning | 30% | Metric causal graph + 3-hop traversal |
| Scientific grounding | 25% | Curated intervention table with real effect sizes + citation validator |
| Knowledge system design | 20% | Two-store retrieval (vector + structured) |
| Conversational intelligence | 15% | Information-gain clarifier + persistent profile |
| Output clarity | 10% | Pydantic-enforced response schema |

55% of the marks are in reasoning and grounding. The vector database is only 20%, and UI is worth nothing — the brief says so directly. Effort should be allocated accordingly: the curated knowledge is the product, the rest is plumbing.

---

## 3. Architecture

### 3.1 Two knowledge stores

Pure RAG produces prose that *sounds* scientific. It does not reliably produce defensible numbers. So knowledge is split:

**Store A — vector DB of literature.** 15–20 markdown files, each a genuine excerpt from FAO / IPCC / ICRISAT / ICAR / CGIAR / peer-reviewed sources, with a frontmatter citation header. Chunked, embedded locally, queried for *mechanism* text and *citation bodies*.

**Store B — structured intervention table.** 25–30 hand-curated JSON rows. Each is one intervention with machine-readable preconditions, effect sizes, time horizons, confidence, tradeoffs, and sources. Filtered in plain Python, not retrieved semantically.

Store B is what makes hallucinated effect sizes structurally impossible — the numbers come from a table, not from the model. Store A supplies the supporting text.

### 3.2 Intervention schema

```json
{
  "id": "farm_pond_bunding",
  "name": "Contour bunding with farm pond",
  "preconditions": {
    "rainfall_mm": [200, 700],
    "land_use": ["cropland", "degraded"],
    "slope": ["gentle", "moderate"]
  },
  "effects": [
    {"metric": "soil_moisture", "delta": "+18-30% in root zone",
     "horizon": "short", "confidence": "high"},
    {"metric": "amphibian_richness", "delta": "+2-5 species",
     "horizon": "medium", "confidence": "medium"},
    {"metric": "soil_organic_carbon", "delta": "+0.1-0.2% absolute",
     "horizon": "long", "confidence": "medium"}
  ],
  "tradeoffs": [
    "Removes 3-5% of cultivable area",
    "Mosquito breeding risk if water stagnates"
  ],
  "mechanism": "Intercepts runoff, extends the infiltration window, raises the shallow water table and creates perennial microhabitat.",
  "sources": [
    {"title": "ICRISAT Watershed Development Impact Assessment 2018",
     "locator": "p.34"}
  ]
}
```

**Two rules, no exceptions.**

1. Never write a number that has not been read in a source. An evaluator will spot-check whether the cited figure appears in the cited paper.
2. Always populate `tradeoffs`. This is what separates a scientist's answer from a brochure's, and it reads directly onto the "non-obvious" criterion.

### 3.3 Metric causal graph

Twelve or so metric nodes, ~30 hand-written edges, each carrying direction and mechanism text.

```python
EDGES = [
  ("soil_organic_carbon", "water_holding_capacity", "+",
   "Each 1% SOC increase raises available water capacity ~1.5-2% by volume"),
  ("water_holding_capacity", "drought_resilience", "+",
   "Extends plant-available water through dry spells"),
  ("drought_resilience", "flowering_duration", "+",
   "Reduces early senescence, lengthening nectar availability"),
  ("flowering_duration", "pollinator_abundance", "+",
   "Continuous forage prevents colony decline between blooms"),
  ("canopy_cover", "soil_temperature", "-",
   "Shading lowers surface temperature 3-6 C, slowing SOC mineralisation"),
  ("field_margin_habitat", "habitat_fragmentation", "-",
   "Linear features act as movement corridors between patches"),
]
```

A depth-3 walk from each primary effect produces the cascade:

```
SOC -> water-holding capacity -> drought resilience
    -> flowering duration -> pollinator abundance
```

This is the 30% criterion made mechanical. The LLM is handed the traced chain and asked to explain it — so a single-variable answer is not reachable, because the chain is already multi-variable before generation starts.

```python
def trace(metric, depth=3, seen=None):
    seen = seen or set()
    if depth == 0 or metric in seen:
        return []
    seen.add(metric)
    return [
        {"link": (src, dst), "sign": sign, "mechanism": mech,
         "downstream": trace(dst, depth - 1, seen)}
        for src, dst, sign, mech in EDGES if src == metric
    ]
```

### 3.4 Pipeline

```
User input (free text or JSON)
  |
  v
[1] State extractor        -> fills EnvironmentalProfile
  |
[2] Completeness gate      -> missing critical var? ask ONE targeted question
  |
[3] Retrieval
      Store B: filter interventions by preconditions
      Store A: hybrid search (BM25 + dense) for mechanism + evidence
  |
[4] Graph reasoner         -> traverse effects, surface synergies + tradeoffs
  |
[5] Ranker                 -> fit x effect size x confidence x feasibility
  |
[6] Structured generator   -> LLM emits validated JSON, then renders
  |
[7] Citation validator     -> drop any source not in the retrieved set
  v
Response
```

Step 7 is roughly ten lines and it guarantees no fabricated citation ever reaches the person grading the project. Cheap insurance on the 25% bucket.

### 3.5 Clarifying questions by information gain

Do not ask for missing fields in declaration order. Ask for the field that most evenly splits the surviving candidate set — that is the question that actually changes the answer.

```python
def next_question(profile, interventions):
    best, best_score = None, 0
    for field in ["soil_organic_carbon", "rainfall_mm", "land_use", "region"]:
        if getattr(profile, field) is not None:
            continue
        gated = [i for i in interventions if field in i["preconditions"]]
        score = min(len(gated), len(interventions) - len(gated))
        if score > best_score:
            best, best_score = field, score
    return QUESTION_TEMPLATES.get(best)
```

One question per turn. Always offer an escape hatch — "if you are not sure, I can work from typical values for your region." Interviewers notice a system that does not interrogate them.

### 3.6 Memory

Two layers.

- **`EnvironmentalProfile`** — persistent facts about the land, updated as the user reveals more.
- **Conversation buffer** — what has been asked, recommended, and rejected.

Forking the profile handles "what about the north field instead?" without losing the original context.

### 3.7 Output contract

```python
class Recommendation(BaseModel):
    action: str
    mechanism: str                  # the "why it works"
    cascade: list[str]              # from graph traversal
    metrics_improved: list[MetricDelta]
    tradeoffs: list[str]
    horizon: Literal["short", "medium", "long"]
    confidence: Literal["high", "medium", "low"]
    sources: list[Source]
```

Schema enforcement means the four mandatory elements from the brief — what to do, why it works, which metric improves, which source — cannot be omitted. If a recommendation survives citation validation with zero valid sources, it is not rendered at all.

---

## 4. Interface

Build one, keep it plain. The brief says it is not looking for UI-heavy applications, but the submission requires a **live demo URL** — someone will open a link and type.

**Build:** chat window, message history, recommendation cards showing the full structured output, and a sidebar displaying the current inferred profile. That sidebar is quietly valuable — it makes memory and state tracking visible rather than buried in code.

**Skip:** custom CSS, animations, landing page, auth, React, dark mode, responsive layout. Zero marks, real hours.

Gradio or Streamlit, default theme, ~60 lines. Deploy to Hugging Face Spaces or Streamlit Community Cloud for the live URL.

The one place to spend extra care: **render the reasoning chain visibly.** Showing `SOC -> water-holding capacity -> drought resilience -> flowering duration -> pollinators` as an explicit chain of arrows is 30% of the score made legible at a glance. Still plain text — no graph visualisation library.

---

## 5. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | |
| Vector DB | Chroma (persistent) | Zero setup, file-backed |
| Embeddings | `all-MiniLM-L6-v2`, local | No API cost, no key, nothing to fail live |
| Store B | Plain JSON | 30 rows does not need Postgres |
| Graph | Hand-written edge list | 30 edges does not need Neo4j |
| Validation | Pydantic | Free schema enforcement on LLM output |
| API | FastAPI (optional) | Only if a JSON endpoint is wanted |
| UI | Gradio | Fastest path to a live URL |

---

## 6. Repo layout

```
darukaa-biodiversity-agent/
├── data/
│   ├── interventions.json      # 25-30 curated rows — the heart
│   └── corpus/                 # 15-20 .md source excerpts
├── kb/
│   ├── ingest.py               # chunk + embed -> Chroma
│   ├── retriever.py            # hybrid search
│   └── graph.py                # metric causal graph
├── agent/
│   ├── profile.py              # EnvironmentalProfile + memory
│   ├── clarify.py              # information-gain question picker
│   ├── reason.py               # candidate filtering + traversal
│   └── respond.py              # LLM call + citation validation
├── app.py                      # Gradio chat
├── cli.py                      # JSON input path
└── README.md
```

Roughly 600 lines total. One weekend.

---

## 7. Build order

**Day 1 — knowledge.** Curate the 25–30 intervention rows and the 15–20 corpus files. Do not rush this; the corpus is the product. Thirty well-sourced rows outscore three hundred shallow ones.

**Day 2 — reasoning, no LLM.** Wire one query end to end with zero model calls: filter candidates, traverse the graph, print the result. If that printout would make a soil scientist nod, the hard part is done. Doing it in this order means that if time runs out, there is still a working reasoning system rather than a half-wired RAG pipeline.

**Day 3 — conversation.** Profile extraction, clarifier, memory, multi-turn loop. Add the LLM for phrasing and extraction only.

**Day 4 — surface and ship.** Gradio UI, citation validator, geo-coordinate bonus, README, deploy.

---

## 8. Requirement coverage

| Brief requirement | Covered by |
|---|---|
| Retrievable knowledge layer, not prompts | Chroma vector store + structured Store B |
| Soil / land use / biodiversity / climate / human impact | Corpus curation spans all five domains |
| Clarifying questions on incomplete input | `agent/clarify.py`, information-gain selection |
| Multi-turn memory | `EnvironmentalProfile` + conversation buffer |
| What / why / which metric / which source | Enforced by `Recommendation` schema |
| ≥3 environmental variables reasoned together | Graph traversal, depth 3 |
| Text input | Gradio chat |
| Structured JSON input | `cli.py` reading a profile from stdin |
| Geo-coordinates (bonus) | lat/lon → agro-ecological zone lookup, ~10 Indian zones, ~20 lines |
| Time horizon + confidence | Fields on every effect in Store B |

---

## 9. README notes

Write it for the evaluator, not for an end user.

- Architecture diagram first.
- A section titled "How knowledge is retrieved and used" that traces one real query end to end: input → profile state → clarifier fired → candidates filtered → chunks retrieved → chain traced → output rendered. The brief asks for exactly this.
- One worked example matching their semi-arid monoculture wheat case (SOC 0.3%, low rainfall).
- Local setup, schema, and CI/CD sections, since the submission guidelines name them.

---

## 10. Submission checklist

- [ ] One Word document (.docx), submitted via the My Jobs / Applied Job page
- [ ] GitHub repository link
- [ ] Live demo URL
- [ ] README overview: architecture, database/schema, local setup, CI/CD
- [ ] Any credentials or notes needed to run it
- [ ] If the repo is private, invite: ankita.dasgupta@, harsh.kumar@, utkarsh.gauniyal@, guneet.mutreja@ (all @darukaa.com)

---

## 11. Failure modes to avoid

- **Vague recommendations.** "Use sustainable practices" fails two criteria at once. The bar is the brief's own example: legume cover crops, +15–25% SOC over 2–3 years, FAO.
- **Single-variable answers.** "Low SOC, so add compost" scores badly. The graph exists to prevent this.
- **Fabricated citations.** The fastest way to lose the 25% grounding bucket. Sources must be passed through from retrieval, never generated.
- **Scope creep into UI.** Explicitly worth zero.
