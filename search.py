#!/usr/bin/env python3
"""Ask Jev which emojis fit a search, then print the matches.

Every emoji gets one yes/no question (a Noul). The answer is a probability
from 0 to 1. Emojis under the cutoff are dropped. The rest are sorted with
the highest probability first.

Jev answers the questions in one request in parallel, but one request cannot
hold the whole catalog. The catalog is split into batches and those batches
run at the same time.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# One batch stays under Jev's 64k token request limit.
# 470 emojis is about 30k tokens, so the whole catalog is 4 requests.
BATCH_SIZE = 470
# A Noul at 0.5 is "yes" as likely as "no". Keep the yes side.
FIT_THRESHOLD = 0.5
MAX_RESULTS = 64
KEYWORD_LIMIT = 48


def key_path() -> Path:
    return Path.home() / ".config" / "jev-emoji" / "api-key"


def load_api_key() -> str:
    env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env:
        return env
    for path in (key_path(), Path.home() / ".config" / "jemoji" / "api-key"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return ""


def has_api_key() -> bool:
    return bool(load_api_key())


def save_api_key(raw: str) -> None:
    text = raw.strip()
    if not text or any(char in text for char in "\n\r\x00"):
        raise RuntimeError("Paste one API key, on one line.")
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def load_catalog(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("Emoji catalog is not a list.")
    catalog = []
    for item in data:
        if not isinstance(item, dict):
            continue
        emoji = str(item.get("e") or "")
        if not emoji:
            continue
        catalog.append({"e": emoji, "k": str(item.get("k") or "")})
    if not catalog:
        raise RuntimeError("Emoji catalog is empty.")
    return catalog


def brief(keywords: str) -> str:
    text = " ".join(keywords.split())
    if len(text) <= KEYWORD_LIMIT:
        return text
    return text[: KEYWORD_LIMIT - 3].rstrip() + "..."


def tag_catalog(catalog: list[dict]) -> list[dict]:
    tagged = []
    for index, item in enumerate(catalog):
        tagged.append(
            {
                "id": f"e{index}",
                "emoji": item["e"],
                "keywords": item["k"],
            }
        )
    return tagged


def chunk(items: list[dict], size: int) -> list[list[dict]]:
    step = max(1, size)
    return [items[start : start + step] for start in range(0, len(items), step)]


def noul_request(query: str, items: list[dict]) -> dict:
    questions = {}
    for item in items:
        meaning = brief(item["keywords"]) or "emoji"
        questions[item["id"]] = {
            "type": "noul",
            "instructions": (
                f"Would a person use {item['emoji']} ({meaning}) to express the search?"
            ),
            "criteria": {
                "true": "Yes. They would choose this emoji.",
                "false": "No. They would not choose this emoji.",
            },
        }
    return {"state": query, "model": MODEL, "questions": questions}


def rank_fits(candidates: list[dict], answers: dict) -> list[dict]:
    results = []
    for item in candidates:
        answer = answers.get(item["id"]) or {}
        if not isinstance(answer, dict) or "noul" not in answer:
            continue
        probability = _float(answer.get("noul"))
        if probability < FIT_THRESHOLD:
            continue
        results.append(
            {
                "e": item["emoji"],
                "k": item["keywords"],
                "p": round(probability, 4),
            }
        )
    results.sort(key=lambda row: row["p"], reverse=True)
    return results[:MAX_RESULTS]


def search(query: str, catalog: list[dict], ask) -> list[dict]:
    text = query.strip()
    if not text:
        return []
    items = tag_catalog(catalog)
    bodies = [noul_request(text, batch) for batch in chunk(items, BATCH_SIZE)]
    if not bodies:
        return []
    answers = {}
    workers = min(8, len(bodies))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for payload in pool.map(ask, bodies):
            answers.update(_answers(payload))
    return rank_fits(items, answers)


def post_systemone(api_key: str, body: dict, timeout: float = 45) -> dict:
    data = json.dumps(body).encode("utf-8")
    last_detail = "Jev is busy. Try again."
    for attempt in range(3):
        request = urllib.request.Request(
            API_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code == 401:
                raise RuntimeError("Jev rejected the API key.") from exc
            if exc.code in (429, 529) and attempt < 2:
                last_detail = f"Jev is busy (HTTP {exc.code})."
                time.sleep(1.5 * (attempt + 1))
                continue
            message = detail.strip() or f"HTTP {exc.code}"
            raise RuntimeError(f"Jev returned HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Jev: {exc.reason}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Jev returned a response that is not an object.")
        return payload
    raise RuntimeError(last_detail)


def emit(ok: bool, results: list[dict] | None = None, error: str = "", extra: dict | None = None) -> None:
    payload = {"ok": ok, "results": results or []}
    if error:
        payload["error"] = error
    if extra:
        payload.update(extra)
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "--has-key":
        emit(True, extra={"hasKey": has_api_key()})
        return 0
    if command == "--save-key":
        try:
            save_api_key(sys.stdin.readline())
        except Exception as exc:
            emit(False, error=str(exc))
            return 1
        emit(True)
        return 0
    query = " ".join(argv[1:]).strip()
    if not query:
        emit(False, error="Type a search.")
        return 2
    api_key = load_api_key()
    if not api_key:
        emit(False, error="No Jev API key.")
        return 2
    try:
        catalog = load_catalog(Path(__file__).with_name("emojis.json"))
        results = search(query, catalog, lambda body: post_systemone(api_key, body))
    except Exception as exc:
        emit(False, error=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    emit(True, results=results)
    return 0


def _answers(payload: dict) -> dict:
    answers = payload.get("answers") if isinstance(payload, dict) else None
    return answers if isinstance(answers, dict) else {}


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
