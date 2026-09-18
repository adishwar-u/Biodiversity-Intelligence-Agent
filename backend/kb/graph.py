"""Metric causal graph: hand-written edges + depth-limited traversal.

Every edge carries a direction and a one-line mechanism, so a traversal
from any primary effect produces a defensible multi-variable cascade
instead of a single-variable claim.
"""
from __future__ import annotations

# (source_metric, target_metric, sign, mechanism)
EDGES: list[tuple[str, str, str, str]] = [
    ("soil_organic_carbon", "water_holding_capacity", "+",
     "Each 1% increase in SOC raises available water capacity roughly 1.5-2% by volume."),
    ("soil_organic_carbon", "soil_erosion", "-",
     "Higher SOC improves aggregate stability, reducing particle detachment and runoff losses."),
    ("water_holding_capacity", "drought_resilience", "+",
     "Extends plant-available water through dry spells between rain events."),
    ("water_holding_capacity", "soil_moisture", "+",
     "Higher storage capacity sustains higher moisture levels between rain events."),
    ("water_holding_capacity", "groundwater_recharge", "+",
     "Improved infiltration and storage raises the share of rainfall that reaches the water table."),
    ("drought_resilience", "flowering_duration", "+",
     "Reduces early senescence, lengthening the window of nectar availability."),
    ("drought_resilience", "crop_yield_stability", "+",
     "Buffers yield against rainfall variability across seasons."),
    ("flowering_duration", "pollinator_abundance", "+",
     "Continuous forage availability prevents colony decline between bloom periods."),
    ("pollinator_abundance", "species_richness", "+",
     "Reliable pollination supports seed set for a wider range of flowering plant species."),
    ("pollinator_abundance", "crop_yield_stability", "+",
     "Insect-pollinated crops show higher and steadier yields with abundant pollinators."),
    ("canopy_cover", "soil_temperature", "-",
     "Shading lowers surface soil temperature by roughly 3-6C, slowing SOC mineralisation."),
    ("soil_temperature", "soil_organic_carbon", "-",
     "Lower soil temperature slows microbial decomposition, allowing SOC to accumulate."),
    ("canopy_cover", "soil_erosion", "-",
     "Canopy interception reduces raindrop impact energy reaching bare soil."),
    ("canopy_cover", "vegetation_structural_diversity", "+",
     "A multi-layered canopy adds vertical habitat niches absent in open land."),
    ("vegetation_structural_diversity", "bird_diversity", "+",
     "More vegetation strata support more foraging and nesting niches."),
    ("vegetation_structural_diversity", "species_richness", "+",
     "Structural complexity generally scales with the number of species an area can support."),
    ("vegetation_structural_diversity", "pest_natural_enemies", "+",
     "Structural complexity provides refuge and overwintering sites for predatory arthropods."),
    ("field_margin_habitat", "habitat_fragmentation", "-",
     "Linear semi-natural features act as movement corridors between habitat patches."),
    ("field_margin_habitat", "pest_natural_enemies", "+",
     "Undisturbed margins host overwintering predator and parasitoid populations."),
    ("field_margin_habitat", "species_richness", "+",
     "Semi-natural margins directly add plant and insect species pools absent from monoculture fields."),
    ("habitat_fragmentation", "species_richness", "-",
     "Fragmentation isolates populations and raises local extinction risk."),
    ("soil_moisture", "amphibian_richness", "+",
     "Sustained soil and surface moisture supports amphibian breeding and dispersal habitat."),
    ("groundwater_recharge", "drought_resilience", "+",
     "Recharged aquifers sustain irrigation and stream baseflow through dry periods."),
    ("groundwater_recharge", "soil_moisture", "+",
     "A higher water table supports capillary rise into the root zone."),
    ("soil_erosion", "water_holding_capacity", "-",
     "Topsoil loss removes the organic-rich layer that holds water."),
    ("amphibian_richness", "species_richness", "+",
     "Amphibians are sensitive indicator taxa; their recovery tracks broader faunal recovery."),
    ("bird_diversity", "pest_natural_enemies", "+",
     "Insectivorous birds add a second trophic layer of pest suppression."),
    ("pest_natural_enemies", "crop_yield_stability", "+",
     "Natural pest control reduces the variance of yield loss from pest outbreaks."),
]

_ALL_METRICS = sorted({s for s, *_ in EDGES} | {d for _, d, *_ in EDGES})


def all_metrics() -> list[str]:
    return list(_ALL_METRICS)


def trace(metric: str, depth: int = 3, _seen: set[str] | None = None) -> list[dict]:
    """Depth-limited walk of downstream effects from `metric`.

    Returns a nested list of {link, sign, mechanism, downstream} dicts —
    the cascade the response layer renders as arrows.
    """
    seen = _seen if _seen is not None else set()
    if depth == 0 or metric in seen:
        return []
    seen = seen | {metric}
    return [
        {
            "link": (src, dst),
            "sign": sign,
            "mechanism": mech,
            "downstream": trace(dst, depth - 1, seen),
        }
        for src, dst, sign, mech in EDGES
        if src == metric
    ]


def flatten_chain(nodes: list[dict]) -> list[str]:
    """Turn a trace() result into flat 'a -> b (+) -> c (+)' path strings, one per leaf path."""
    paths: list[str] = []

    def walk(node: dict, path_so_far: list[str]):
        src, dst = node["link"]
        step = f"{dst} ({node['sign']})"
        new_path = path_so_far + [step]
        if node["downstream"]:
            for child in node["downstream"]:
                walk(child, new_path)
        else:
            paths.append(" -> ".join(new_path))

    for node in nodes:
        src = node["link"][0]
        walk(node, [src])

    return paths


if __name__ == "__main__":
    import json

    cascade = trace("soil_organic_carbon", depth=3)
    for path in flatten_chain(cascade):
        print(path)
