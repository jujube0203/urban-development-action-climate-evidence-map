"""Shared API and CSV routines for the three sequential research steps."""

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUTPUT = HERE / "output"
SOURCE_FIELDS = ["Title", "Year", "DOI", "Abstract"]
TEMPERATURE = 0.3

# Model identifiers and request settings follow the working extraction scripts.
# Credentials are read from the environment and are never saved in this package.
PROVIDERS = {
    "DSflash": {
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "thinking": {"thinking": {"type": "disabled"}},
    },
    "Qwenflash": {
        "model": "qwen3.8-flash",
        "base_url": os.getenv("QWEN_BASE_URL", ""),
        "key_env": "QWEN_API_KEY",
        "thinking": {"enable_thinking": False},
    },
    "Zhipu": {
        "model": "glm-5.2",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_env": "ZHIPU_API_KEY",
        "thinking": {"thinking": {"type": "disabled"}},
    },
}


def read_csv(path):
    csv.field_size_limit(100_000_000)
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"Missing or duplicate CSV columns: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protocol_hash(input_path, prompt, provider, run, dependency_path=None):
    settings = PROVIDERS[provider]
    payload = [sha256(input_path), prompt, provider, run, settings["model"],
               settings["base_url"], TEMPERATURE,
               sha256(dependency_path) if dependency_path else ""]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def call_json(provider_name, prompt, content, max_tokens):
    provider = PROVIDERS[provider_name]
    key = os.getenv(provider["key_env"], "").strip()
    if not key:
        raise ValueError(f"Set {provider['key_env']} before processing records")
    if not provider["base_url"]:
        raise ValueError(f"Set QWEN_BASE_URL before processing Qwen records")
    payload = {
        "model": provider["model"],
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
        **provider["thinking"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
        ],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    for attempt in range(5):
        request = urllib.request.Request(
            url, data=data,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"].strip()
            if text.startswith("```") and text.endswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)[:-3].strip()
            result = json.loads(text)
            if isinstance(result, dict) and result and any(
                value not in ("", None, [], {}) for value in result.values()
            ):
                return "ok", result
        except urllib.error.HTTPError as error:
            if error.code == 400:
                detail = error.read().decode("utf-8", errors="replace")
                if re.search(r'"code"\s*:\s*"?1301', detail):
                    return "skipped_content_filter", {}
            if error.code not in {408, 409, 429, 500, 502, 503, 504}:
                return "pending_retry", {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError,
                KeyError, IndexError, TypeError, AttributeError):
            pass
        if attempt < 4:
            time.sleep(min(2 ** (attempt + 1), 30))
    return "pending_retry", {}


def provider_run_rows(stage, input_path, source, fields, prompt, provider, run,
                      make_content, dependency_path=None):
    """One independent provider/run file, resumed from its saved CSV."""
    if provider not in PROVIDERS or run not in (1, 2, 3):
        raise ValueError("Choose DSflash, Qwenflash or Zhipu and run 1, 2 or 3")
    output = OUTPUT / stage / f"{provider}_run{run}.csv"
    columns = ["row_id", *SOURCE_FIELDS, *fields, "Status",
               "model_output_json", "protocol_sha256"]
    fingerprint = protocol_hash(input_path, prompt, provider, run,
                                dependency_path)
    saved = {}
    if output.exists():
        old_columns, previous = read_csv(output)
        if old_columns != columns:
            raise ValueError(f"Output schema changed: {output}")
        for row in previous:
            index = int(row["row_id"])
            if (index < 1 or index > len(source)
                    or row["DOI"] != source[index - 1]["DOI"]
                    or row["protocol_sha256"] != fingerprint):
                raise ValueError(f"Input or prompt changed: {output}")
            saved[index] = row
    rows = []
    for index, document in enumerate(source, 1):
        old = saved.get(index)
        if old and old["Status"] in {"ok", "skipped_content_filter"}:
            rows.append(old)
            continue
        content = make_content(index, document)
        if content is None:
            status, result = "waiting_round1", {}
        else:
            status, result = call_json(provider, prompt, content, 1024)
        projected = {field: result.get(field, "") for field in fields}
        rows.append({
            "row_id": index, **{key: document[key] for key in SOURCE_FIELDS},
            **{key: value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False) for key, value in projected.items()},
            "Status": status,
            "model_output_json": json.dumps(result, ensure_ascii=False) if result else "",
            "protocol_sha256": fingerprint,
        })
        if index % 50 == 0:
            write_csv(output, columns, rows)
            print(f"{stage} {provider} run {run}: {index}/{len(source)}", flush=True)
    write_csv(output, columns, rows)
    print(f"Saved {output}; {sum(row['Status'] == 'ok' for row in rows)}/{len(rows)} successful")
