"""Step 2b: form one audited Round 1 record before any Round 2 calls."""

from collections import Counter
import json
import re
import unicodedata

from api_common import OUTPUT, SOURCE_FIELDS, read_csv, write_csv

PROVIDERS = ("DSflash", "Qwenflash", "Zhipu")
RUNS = (1, 2, 3)
FIELDS = ("city_name", "country_name", "development_topic_original", "action_original")


def key(value):
    value = unicodedata.normalize("NFKD", value.strip().casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def clean(field, value):
    if value is None:
        return None
    value = " ".join(value.split())
    if key(value) in {"na", "n a", "null", "none", "unknown"}:
        return None
    if field == "country_name":
        value = {
            "usa": "United States", "us": "United States",
            "united states of america": "United States",
            "the united state": "United States",
            "uk": "United Kingdom", "britain": "United Kingdom",
            "great britain": "United Kingdom",
            "the united kingdom": "United Kingdom",
        }.get(key(value), value)
    return value


def representative(values):
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value.casefold(), value))


def vote(field, by_model):
    """Two of three within a model; two model votes; then pooled plurality."""
    pooled = [value for values in by_model.values() for value in values
              if value is not None]
    if not pooled:
        return "", "no_data", "no_saved_vote", 0, ""
    model_votes = []
    for provider in PROVIDERS:
        values = [value for value in by_model[provider] if value is not None]
        counts = Counter(key(value) for value in values)
        winning = [name for name, count in counts.items() if count >= 2]
        if len(winning) == 1:
            model_votes.append(winning[0])
    model_counts = Counter(model_votes)
    agreed = [name for name, count in model_counts.items() if count >= 2]
    if len(agreed) == 1:
        chosen, rule = agreed[0], "two_model_majority"
    else:
        counts = Counter(key(value) for value in pooled)
        highest = max(counts.values())
        winning = [name for name, count in counts.items() if count == highest]
        if len(winning) != 1:
            options = sorted(representative([value for value in pooled
                                             if key(value) == name])
                             for name in winning)
            return "", "indecisive", "pooled_tie", len(pooled), json.dumps(
                options, ensure_ascii=False)
        chosen, rule = winning[0], "pooled_plurality"
    variants = [value for value in pooled if key(value) == chosen]
    return representative(variants), "decisive", rule, len(pooled), ""


def read_run(provider, run, source):
    path = OUTPUT / "round1" / f"{provider}_run{run}.csv"
    columns, rows = read_csv(path)
    required = {"row_id", *SOURCE_FIELDS, *FIELDS, "Status"}
    if not required.issubset(columns) or len(rows) != len(source):
        raise ValueError(f"Round 1 output is missing or incomplete: {path}")
    result = []
    for index, (saved, original) in enumerate(zip(rows, source), 1):
        if (saved["row_id"] != str(index)
                or any(saved[field] != original[field] for field in SOURCE_FIELDS)):
            raise ValueError(f"Source mismatch: {path}, row {index}")
        if saved["Status"] == "ok":
            result.append({field: clean(field, saved[field]) for field in FIELDS})
        elif saved["Status"] in {"skipped_content_filter", "pending_retry"}:
            result.append(None)
        else:
            raise ValueError(f"Unexpected status in {path}, row {index}")
    return result


def guard_pair(row, records, left, right, label):
    first = row[f"{left}_consensus"]
    second = row[f"{right}_consensus"]
    if not first or not second:
        row[f"{label}_pair_status"] = "incomplete"
        return
    supported = any(
        record is not None
        and key(record[left] or "") == key(first)
        and key(record[right] or "") == key(second)
        for record in records
    )
    row[f"{label}_pair_status"] = "jointly_supported" if supported else "no_joint_response"
    if not supported:
        for field in (left, right):
            row[f"{field}_consensus"] = ""
            row[f"{field}_vote_status"] = "indecisive"
            row[f"{field}_vote_rule"] = "no_joint_response"


def main():
    source_path = OUTPUT / "screened_included.csv"
    columns, source = read_csv(source_path)
    if columns != SOURCE_FIELDS:
        raise ValueError(f"Expected {SOURCE_FIELDS} in {source_path}")
    runs = {(provider, run): read_run(provider, run, source)
            for provider in PROVIDERS for run in RUNS}
    output_rows = []
    for index, original in enumerate(source):
        row = dict(original)
        records = [runs[(provider, run)][index]
                   for provider in PROVIDERS for run in RUNS]
        for field in FIELDS:
            by_model = {
                provider: [None if runs[(provider, run)][index] is None
                           else runs[(provider, run)][index][field]
                           for run in RUNS]
                for provider in PROVIDERS
            }
            value, status, rule, count, ties = vote(field, by_model)
            row[f"{field}_consensus"] = value
            row[f"{field}_vote_status"] = status
            row[f"{field}_vote_rule"] = rule
            row[f"{field}_saved_votes"] = count
            row[f"{field}_tied_values_json"] = ties
        guard_pair(row, records, "city_name", "country_name", "location")
        guard_pair(row, records, "development_topic_original", "action_original",
                   "purpose_action")
        output_rows.append(row)
    fields = [*SOURCE_FIELDS]
    for field in FIELDS:
        fields.extend(f"{field}_{suffix}" for suffix in (
            "consensus", "vote_status", "vote_rule", "saved_votes",
            "tied_values_json"))
    fields.extend(("location_pair_status", "purpose_action_pair_status"))
    path = OUTPUT / "round1_consensus.csv"
    write_csv(path, fields, output_rows)
    print(f"Saved {len(output_rows)} Round 1 consensus records: {path}")


if __name__ == "__main__":
    main()
