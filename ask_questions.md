# Try It — Example Chat Inputs

Ready-to-paste land descriptions for the **Biodiversity Intelligence Agent**
chat (`http://localhost:5173`). Each numbered example is a complete
profile, so it skips straight to recommendation cards — no back-and-forth
needed.

## Field cheat sheet

| Field | Format | Example |
|---|---|---|
| Soil organic carbon (SOC) | a number + `%` | `SOC 0.3%` |
| Rainfall | a number + `mm`, or a word | `rainfall 550mm` / `rainfall low` |
| Land use | cropland/farmland, degraded/barren, pasture, grassland, forest | `wheat cropland` |
| Slope *(optional)* | flat, gentle, moderate, steep | `gentle slope` |
| Region *(optional)* | a named zone, or just a climate word | `semi-arid deccan` / `semi-arid` |

## One-shot examples

Paste any of these and you'll get 3–4 recommendation cards immediately.
Different regions and conditions pull different interventions — try a
few and compare.

1. `Wheat cropland in the semi-arid deccan region, SOC 0.3%, rainfall 550mm, gentle slope`
2. `Degraded barren land in arid rajasthan, SOC 0.15%, rainfall 300mm, steep slope`
3. `Grazing pasture in central highlands, SOC 0.4%, rainfall 900mm, flat land`
4. `Rice cropland in the indo-gangetic plains, SOC 0.5%, rainfall 1000mm, gentle slope`
5. `Forest land in the western ghats, SOC 1.2%, rainfall 2500mm, steep slope`
6. `Maize farmland in coastal andhra, SOC 0.55%, rainfall 1100mm, moderate slope`
7. `Grassland in north-east hills, SOC 1.0%, rainfall 2000mm, moderate slope`
8. `Eroded wasteland near a river in kutch, SOC 0.15%, rainfall low, flat`
9. `Monoculture wheat cropland, semi-arid, SOC 0.3%, rainfall low` — *the brief's own worked example*
10. `Cropland near a watershed, moderate slope, rainfall 650mm, SOC 0.35%` — *no region given, still works since region is optional*

> **Worth comparing:** #5 (Western Ghats forest, high rainfall) vs.
> #2 (arid Rajasthan, steep, degraded) — near-opposite conditions,
> near-opposite recommendation sets.

## Multi-turn flows

These don't resolve in one message — they show off the clarifying
questions and the "use typical values" fallback instead.

11. `I have some land I want to improve`
    → too vague; it'll ask one question at a time, starting with whatever
    narrows the recommendation set down the most.
12. `semi-arid deccan, not sure about the rest`
    → names a region, then auto-fills rainfall/SOC/land use from typical
    values for that zone.
