"""Merge Round 1 consensus and nine Round 2 responses by linked-record votes."""

from collections import Counter
import json
import re
import unicodedata

from api_common import OUTPUT, SOURCE_FIELDS, read_csv, write_csv

PROVIDERS = ("DSflash", "Qwenflash", "Zhipu")
RUNS = (1, 2, 3)
PROVIDER_RUNS = {"DSflash": RUNS, "Qwenflash": RUNS, "Zhipu": RUNS}
FIELDS_R1 = ("city_name", "country_name", "development_topic_original", "action_original")
FIELDS_R2 = (
    "development_topic", "development_topic_original",
    "Major_categories_action", "Sub_categories_Action", "action_original",
    "mitigation", "adaptation", "Relation_nature", "Research_type",
)
FIELDS = ("city_name", "country_name", *FIELDS_R2)
DEVELOPMENT = [
    "Resource Efficiency and Circularity", "Coastal and Marine Sustainability",
    "Sustainable Infrastructure and Urban Development",
    "Biodiversity and Ecosystem Health", "Green Energy and Economic Transition",
    "Food Security and Sustainable Agriculture", "Pollution Control and Public Health",
    "Social Equity and Inclusive Services", "Transport Accessibility and Efficiency",
    "Flood Resilience and Stormwater Management", "Thermal Comfort and Heat Reduction",
    "Urban Resilience and Risk Reduction", "Water Safety and Reliability",
]
ACTION = {
    "Agriculture & Food Systems": "Agroforestry; Dietary shifts; Improved cropland management; Reduce food loss and food waste; Soil health management",
    "Construction & Building": "Change in construction materials; Efficient buildings; Energy-demand avoidance; High-performance new building; Improvement building stock",
    "Energy Solutions": "Bioenergy; District heating & cooling networks; Energy efficiency; Energy supply / Renewables; Fuel switching; Geothermal energy; Hydropower; Resilient power systems; Solar energy; Wind energy",
    "Land Use & Spatial Planning": "Climate-sensitive spatial planning; Coastal zone management; Land use and spatial planning; Urban design and public-space configuration; Urban form, density and mixed-use development; Zoning and urban growth management",
    "Nature-based & Ecosystem": "Ecological connectivity; Ecosystem restoration; Forest-based adaptation; Green and blue infrastructure; Green infrastructure; Ocean ecosystem services",
    "Resilience Enablers/Tools": "Climate services; Coastal defense and hardening; Disaster risk management; Early warning and preparedness; Emergency response and evacuation; Post-disaster recovery and relocation; Social safety nets",
    "Transition knowledge/Government": "Integrated Knowledge/Governance; Policy, market & funding instruments",
    "Transport & Mobility": "Electric light-duty vehicle tech; Fuel-efficient light-duty vehicle tech; Integrated modal-demand shift; Shared automated electric mobility systems; Non-motorized transport; Public transport; Transport fuel switching",
    "Waste & Circular Economy": "Circular material flows; Enhanced recycling; Solid waste management; Waste prevention, minimization and management",
    "Water Management": "Integrated Water Management; Stormwater Management; Water use efficiency",
}
ACTION = {major: [item.strip() for item in names.split(";")]
          for major, names in ACTION.items()}
RELATIONS = ("causal", "associational", "estimated", "predicted")
RESEARCH_TYPES = ("Empirical", "Mixed", "Non-empirical", "Unclear")


def key(value):
    value = unicodedata.normalize("NFKD", value.strip().casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def labels():
    maps = {
        "development_topic": {key(name): name for name in DEVELOPMENT},
        "Major_categories_action": {key(name): name for name in ACTION},
        "Sub_categories_Action": {
            key(name): name for names in ACTION.values() for name in names
        },
    }
    maps["development_topic"].update({
        key(old): new for old, new in {
            "Circular Economy": "Resource Efficiency and Circularity",
            "Coastal and Marine": "Coastal and Marine Sustainability",
            "Coastal & Marine": "Coastal and Marine Sustainability",
            "Costal and Marine": "Coastal and Marine Sustainability",
            "Development & Infrastructure": "Sustainable Infrastructure and Urban Development",
            "Ecosystem & Biodiversity": "Biodiversity and Ecosystem Health",
            "Energy Transition & green economy": "Green Energy and Economic Transition",
            "Food & Agriculture": "Food Security and Sustainable Agriculture",
            "Health & Pollution": "Pollution Control and Public Health",
            "Poverty & Social Equity": "Social Equity and Inclusive Services",
            "Transport & Mobility": "Transport Accessibility and Efficiency",
            "Urban Flooding & Stormwater Risk": "Flood Resilience and Stormwater Management",
            "Urban Heat Environment & Thermal Comfort": "Thermal Comfort and Heat Reduction",
            "Urban Resilience": "Urban Resilience and Risk Reduction",
            "Water Security & Management": "Water Safety and Reliability",
        }.items()
    })
    for old in ("Urban afforestation", "Urban parks and green spaces",
                "Urban trees and afforestation", "Green roofs and façades"):
        maps["Sub_categories_Action"][key(old)] = "Green infrastructure"
    maps["Sub_categories_Action"][key(
        "Risk reduction and protective measures"
    )] = "Disaster risk management"
    return maps


LABELS = labels()
SUB_PARENT = {key(sub): major for major, names in ACTION.items() for sub in names}


def normalize(field, raw):
    # None abstains; an actual empty string is a valid saved vote.
    if raw is None:
        return None
    value = raw.strip() if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    if value == "":
        return ""
    if key(value) in {"na", "n a", "null", "none"}:
        return None
    if field in LABELS:
        norm = key(value)
        if field == "Major_categories_action" and norm in SUB_PARENT:
            return SUB_PARENT[norm]
        return LABELS[field].get(norm)
    if field in {"mitigation", "adaptation"}:
        return value.casefold() if value.casefold() in {"positive", "negative"} else None
    if field == "Research_type":
        return {**{key(item): item for item in RESEARCH_TYPES},
                key("Observed"): "Empirical", key("Estimated"): "Empirical"}.get(key(value))
    if field == "Relation_nature":
        pieces = [piece.strip().casefold() for piece in value.split(";")]
        if pieces == ["unclear"]:
            return "unclear"
        if pieces and len(set(pieces)) == len(pieces) and all(
            piece in RELATIONS for piece in pieces
        ):
            return "; ".join(piece for piece in RELATIONS if piece in pieces)
        return None
    if field == "country_name":
        return {
            "mexico": "Mexico",
            "united states of america": "United States",
            "the united state": "United States",
            "usa": "United States",
            "the united kingdom": "United Kingdom",
            "uk": "United Kingdom",
            "great britain": "United Kingdom",
        }.get(key(value), value)
    return " ".join(value.split())




def linked_candidates(round1, round2):
    """Create links from one Round 2 response and the shared location record."""
    if round1 is None or round2 is None:
        return []
    purpose = normalize("development_topic_original", round2.get("development_topic_original"))
    action = normalize("action_original", round2.get("action_original"))
    topic = normalize("development_topic", round2.get("development_topic"))
    sub = normalize("Sub_categories_Action", round2.get("Sub_categories_Action"))
    if not all((purpose, action, topic, sub)):
        return []
    major = SUB_PARENT[key(sub)]
    raw_major = normalize(
        "Major_categories_action", round2.get("Major_categories_action")
    )
    record = {
        "city_name": normalize("city_name", round1.get("city_name")) or "",
        "country_name": normalize("country_name", round1.get("country_name")) or "",
        "development_topic": topic,
        "development_topic_original": purpose,
        "Major_categories_action": major,
        "Sub_categories_Action": sub,
        "action_original": action,
        "mitigation": normalize("mitigation", round2.get("mitigation")) or "",
        "adaptation": normalize("adaptation", round2.get("adaptation")) or "",
        "Relation_nature": normalize(
            "Relation_nature", round2.get("Relation_nature")
        ) or "",
        "Research_type": normalize("Research_type", round2.get("Research_type")) or "",
        "action_pair_check": (
            "consistent" if raw_major == major else
            "raw_major_differs_from_subcategory_parent"
        ),
    }
    return [
        {"key": (topic, sub, dimension, record[dimension]), "record": record}
        for dimension in ("mitigation", "adaptation")
        if record[dimension] in ("positive", "negative")
    ]


def show_link_values(values):
    """Keep tied links aligned by their shared [1], [2], ... indices."""
    if not values:
        return ""
    if len(values) == 1:
        return str(values[0])
    return " || ".join(f"[{index}] {value}" for index, value in enumerate(values, 1))


def linkage_vote(candidate_runs):
    """Select intact categorical links separately for mitigation and adaptation."""
    model_votes = {}
    for provider in PROVIDERS:
        counts = Counter(
            edge["key"] for run in PROVIDER_RUNS[provider]
            for edge in candidate_runs[(provider, run)]
        )
        required = 2
        model_votes[provider] = {
            link for link, count in counts.items() if count >= required
        }
    model_agreed = {
        link for link in set().union(*model_votes.values())
        if sum(link in choices for choices in model_votes.values()) >= 2
    }
    pooled = Counter(
        edge["key"] for edges in candidate_runs.values() for edge in edges
    )
    maximum = max(pooled.values(), default=0)
    final_keys = []
    for dimension in ("mitigation", "adaptation"):
        agreed = [link for link in model_agreed if link[2] == dimension]
        eligible = agreed or [
            link for link, count in pooled.items()
            if link[2] == dimension and count >= 2
        ]
        best = max((pooled[link] for link in eligible), default=0)
        final_keys.extend(link for link in eligible if pooled[link] == best)
    final_keys.sort(key=lambda link: (link[2], link[0], link[1], link[3]))
    final = []
    for link in final_keys:
        supporters = [
            (provider, run, edge["record"])
            for provider in PROVIDERS for run in PROVIDER_RUNS[provider]
            for edge in candidate_runs[(provider, run)] if edge["key"] == link
        ]
        phrase_counts = Counter((
            key(record["development_topic_original"]),
            key(record["action_original"]),
        ) for _, _, record in supporters)
        supporters.sort(key=lambda item: (
            -phrase_counts[(
                key(item[2]["development_topic_original"]),
                key(item[2]["action_original"]),
            )],
            -(link in model_votes[item[0]]),
            PROVIDERS.index(item[0]), item[1],
        ))
        provider, run, record = supporters[0]
        final.append({
            **record,
            "outcome_dimension": link[2],
            "outcome_direction": link[3],
            "representative_provider": provider,
            "representative_run": run,
            "model_support": "+".join(
                name for name, choices in model_votes.items() if link in choices
            ),
            "raw_support_count": pooled[link],
            "selection_basis": (
                "model_level_agreement" if link in model_agreed
                else "pooled_plurality_only"
            ),
        })
    return model_agreed, maximum, final


def read_run(stage, provider, run, source):
    path = OUTPUT / stage / f"{provider}_run{run}.csv"
    _, rows = read_csv(path)
    if len(rows) != len(source):
        raise ValueError(f"Row count differs: {path}")
    result = []
    for index, (saved, original) in enumerate(zip(rows, source), 1):
        if (saved["row_id"] != str(index)
                or any(saved[field] != original[field] for field in SOURCE_FIELDS)):
            raise ValueError(f"Source mismatch: {path}, row {index}")
        if saved["Status"] == "ok":
            raw = json.loads(saved["model_output_json"])
            result.append(raw if isinstance(raw, dict) else None)
        elif saved["Status"] in {
            "skipped_content_filter", "waiting_round1", "pending_retry"
        }:
            result.append(None)
        else:
            raise ValueError(f"Unexpected status in {path}, row {index}")
    return result


def main():
    source_path = OUTPUT / "screened_included.csv"
    source_columns, source = read_csv(source_path)
    if source_columns != SOURCE_FIELDS:
        raise ValueError(f"Expected {SOURCE_FIELDS} in {source_path}")
    r1_path = OUTPUT / "round1_consensus.csv"
    r1_columns, r1_rows = read_csv(r1_path)
    if (len(r1_rows) != len(source)
            or not {f"{field}_consensus" for field in FIELDS_R1}.issubset(r1_columns)):
        raise ValueError(f"Round 1 consensus is missing or incomplete: {r1_path}")
    for index, (saved, original) in enumerate(zip(r1_rows, source), 1):
        if any(saved[field] != original[field] for field in SOURCE_FIELDS):
            raise ValueError(f"Source mismatch: {r1_path}, row {index}")
    runs = {
        (provider, run): read_run("round2", provider, run, source)
        for provider in PROVIDERS for run in PROVIDER_RUNS[provider]
    }
    merged = []
    for index, base in enumerate(source):
        row = dict(base)
        round1 = {field: r1_rows[index][f"{field}_consensus"]
                  for field in FIELDS_R1}
        candidate_runs = {
            (provider, run): linked_candidates(
                round1, runs[(provider, run)][index],
            )
            for provider in PROVIDERS for run in PROVIDER_RUNS[provider]
        }
        model_agreed, maximum, final = linkage_vote(candidate_runs)
        row["model_level_link_count"] = len(model_agreed)
        row["pooled_max_supporting_responses"] = maximum
        row["final_link_count"] = len(final)
        dimensions = Counter(record["outcome_dimension"] for record in final)
        row["link_consensus_status"] = (
            "no_repeated_complete_link" if not final else
            "tied_pooled_plurality_review" if any(count > 1 for count in dimensions.values()) else
            "multiple_outcome_dimensions" if len(final) > 1 else
            final[0]["selection_basis"]
        )
        for field in FIELDS:
            row[f"{field}_consensus"] = show_link_values(
                [record[field] for record in final]
            )
        for field in (
            "outcome_dimension", "outcome_direction", "representative_provider",
            "representative_run", "model_support", "raw_support_count",
            "selection_basis", "action_pair_check",
        ):
            row[f"{field}_link"] = show_link_values(
                [record[field] for record in final]
            )
        row["final_link_records_json"] = (
            json.dumps(final, ensure_ascii=False, separators=(",", ":"))
            if final else ""
        )
        merged.append(row)
    fields = [
        *SOURCE_FIELDS,
        "model_level_link_count", "pooled_max_supporting_responses",
        "final_link_count", "link_consensus_status",
        *[f"{field}_consensus" for field in FIELDS],
        *[f"{field}_link" for field in (
            "outcome_dimension", "outcome_direction", "representative_provider",
            "representative_run", "model_support", "raw_support_count",
            "selection_basis", "action_pair_check",
        )],
        "final_link_records_json",
    ]
    path = OUTPUT / "consensus_linkage_9vote.csv"
    write_csv(path, fields, merged)
    print(f"Saved {len(merged)} document records: {path}")


if __name__ == "__main__":
    main()
