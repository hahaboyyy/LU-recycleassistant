"""Shared scoring helpers for evaluation scripts (dev set and formal test set).

Kept in the package rather than in scripts/ so both ``run_dev_set.py`` and
``run_batch.py`` classify failures exactly the same way.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

#: Module B's four outcomes mapped onto Role A's four action branches.
STATUS_TO_ACTION: dict[str, str] = {
    "matched": "give_advice",
    "ambiguous": "clarify_item",
    "out_of_scope": "out_of_scope",
    "unresolved": "unresolved",
}

#: Wrong in two very different directions; never collapse them into one score.
KIND_HELP = {
    "ok": "outcome matched the expected action",
    "abstained": "asked although the case had a clear answer (recoverable, costs a round)",
    "over_confident": "answered although the case needed a question (dangerous)",
    "wrong_outcome": "outcome differs in another way (e.g. out_of_scope missed)",
    "error": "the call failed (network/auth/parse)",
}

#: Images below this long edge are treated as data-limited, not as system errors.
DATA_LIMITED_EDGE_PX = 200


def classify(expected_action: str, status: str) -> str:
    if status == "ERROR":
        return "error"
    got = STATUS_TO_ACTION.get(status, "")
    if got == expected_action:
        return "ok"
    if expected_action == "give_advice" and got == "clarify_item":
        return "abstained"
    if expected_action == "clarify_item" and got == "give_advice":
        return "over_confident"
    return "wrong_outcome"


def image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as probe:
            return probe.size
    except OSError:
        return 0, 0


def write_predictions(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Three separate numbers: accuracy (excluding data-limited), abstention, over-confidence."""
    rows = list(rows)
    kinds = Counter(r.get("error_kind", "ok") for r in rows)
    limited = [r for r in rows if r.get("data_limited") == "yes"]
    scored = [r for r in rows if r.get("data_limited") != "yes"]
    id_rows = [r for r in rows if r.get("id_match") in ("yes", "no")]
    id_ok = sum(1 for r in id_rows if r["id_match"] == "yes")
    lat = [float(r["latency_ms"]) for r in rows if str(r.get("latency_ms", "")).isdigit()]
    return {
        "cases": len(rows),
        "data_limited": len(limited),
        "ok": kinds.get("ok", 0),
        "abstained": kinds.get("abstained", 0),
        "over_confident": kinds.get("over_confident", 0),
        "wrong_outcome": kinds.get("wrong_outcome", 0),
        "errors": kinds.get("error", 0),
        "accuracy_excl_limited": round(kinds.get("ok", 0) / len(scored), 4) if scored else None,
        "abstention_rate": round(kinds.get("abstained", 0) / len(scored), 4) if scored else None,
        "over_confident_rate": round(kinds.get("over_confident", 0) / len(rows), 4) if rows else None,
        "item_id_accuracy": round(id_ok / len(id_rows), 4) if id_rows else None,
        "latency_p50_ms": sorted(lat)[len(lat) // 2] if lat else None,
        "latency_max_ms": max(lat) if lat else None,
    }
