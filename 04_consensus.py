"""Merge each round's three-model, three-run outputs by the saved vote rule."""

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import unicodedata

from api_common import OUTPUT, SOURCE_FIELDS, read_csv, write_csv

PROVIDERS = ("DSflash", "Qwenflash", "Zhipu")
RUNS = (1, 2, 3)
FIELDS_R1 = ("city_name", "country_name", "Action_motivation", "Primary_action")
FIELDS_R2 = (
    "development_topic", "development_topic_original",
    "Major_categories_action", "Sub_categories_Action", "action_original",
    "mitigation", "adaptation", "Relation_nature", "Research_type",
)
FIELDS = (*FIELDS_R1, *FIELDS_R2)
DEVELOPMENT = [
    "Circular Economy", "Coastal and Marine", "Development & Infrastructure",
    "Ecosystem & Biodiversity", "Energy Transition & green economy",
    "Food & Agriculture", "Health & Pollution", "Poverty & Social Equity",
    "Transport & Mobility", "Urban Flooding & Stormwater Risk",
    "Urban Heat Environment & Thermal Comfort", "Urban Resilience",
    "Water Security & Management",
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
RESEARCH_TYPES = ("Observed", "Estimated", "Mixed", "Non-empirical", "Unclear")


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
        key("Costal and Marine"): "Coastal and Marine",
        key("Coastal & Marine"): "Coastal and Marine",
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
        return {key(item): item for item in RESEARCH_TYPES}.get(key(value))
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


def vote_key(value, field):
    if field in {"city_name", "country_name", "Action_motivation", "Primary_action",
                 "development_topic_original", "action_original"}:
        return key(value)
    return value


def representatives(values, field):
    buckets = defaultdict(list)
    for value in values:
        buckets[vote_key(value, field)].append(value)
    count = Counter({name: len(items) for name, items in buckets.items()})
    winners = sorted(name for name, n in count.items() if n == max(count.values()))
    shown = []
    for name in winners:
        variants = Counter(buckets[name])
        shown.append(sorted(variants, key=lambda item: (
            -variants[item], item.casefold(), item
        ))[0])
    return shown


def group_mode(values, field):
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return sorted(representatives(valid, field),
                  key=lambda item: (item.casefold(), item))[0]


def vote(field, grouped):
    modes = [group_mode(group, field) for group in grouped]
    available_modes = [mode for mode in modes if mode is not None]
    all_valid = [value for group in grouped for value in group if value is not None]
    if not all_valid:
        return "", "No data", "no_saved_vote", 0
    if len(available_modes) == 1:
        winners, rule = [available_modes[0]], "single_model_mode"
    elif len(set(vote_key(item, field) for item in available_modes)) == 1:
        winners, rule = [available_modes[0]], "model_modes_agree"
    elif len(available_modes) == 3:
        freq = Counter(vote_key(item, field) for item in available_modes)
        same = [item for item in available_modes if freq[vote_key(item, field)] >= 2]
        if same:
            winners, rule = [same[0]], "two_model_modes_agree"
        else:
            winners, rule = representatives(all_valid, field), "all_round_frequency_fallback"
    else:
        winners, rule = representatives(all_valid, field), "all_round_frequency_fallback"
    return (
        ",".join(sorted(winners, key=lambda item: (item.casefold(), item))),
        "Indecisive" if len(winners) > 1 else "Decisive",
        rule, len(all_valid),
    )


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
    runs = {
        (stage, provider, run): read_run(stage, provider, run, source)
        for stage in ("round1", "round2")
        for provider in PROVIDERS for run in RUNS
    }
    merged = []
    for index, base in enumerate(source):
        row = dict(base)
        for field in FIELDS:
            stage = "round1" if field in FIELDS_R1 else "round2"
            groups = []
            for provider in PROVIDERS:
                values = []
                for run in RUNS:
                    raw_record = runs[(stage, provider, run)][index]
                    raw = raw_record.get(field) if raw_record is not None else None
                    values.append(normalize(field, raw))
                groups.append(values)
            choice = vote(field, groups)
            for suffix, value in zip(
                ("consensus", "status", "vote_rule", "available"), choice
            ):
                row[f"{field}_{suffix}"] = value
        major = row["Major_categories_action_consensus"]
        sub = row["Sub_categories_Action_consensus"]
        if (row["Major_categories_action_status"] == "Indecisive"
                or row["Sub_categories_Action_status"] == "Indecisive"):
            row["action_pair_check"] = "indecisive_vote"
        elif not major or not sub:
            row["action_pair_check"] = "incomplete_pair"
        else:
            parent = SUB_PARENT.get(key(sub))
            row["action_pair_check"] = (
                "consistent" if major == parent else "review_major_subcategory"
            )
        merged.append(row)
    fields = [
        *SOURCE_FIELDS,
        *[f"{field}_{suffix}" for field in FIELDS
          for suffix in ("consensus", "status", "vote_rule", "available")],
        "action_pair_check",
    ]
    path = OUTPUT / "consensus_3x3.csv"
    write_csv(path, fields, merged)
    print(f"Saved {len(merged)} document records: {path}")


if __name__ == "__main__":
    main()
