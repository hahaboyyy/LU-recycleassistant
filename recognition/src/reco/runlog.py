"""Append-only JSONL run log + usage summary.

This is the evidence base for the "实际用量与耗时" part of the report and the
input module E analyses. One line per API call, no image content, no user data.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable


class RunLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a crashed write must not break the summary
        return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    low = int(k)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def summarize(
    records: Iterable[dict[str, Any]],
    price_in: float | None = None,
    price_out: float | None = None,
) -> dict[str, Any]:
    """Aggregate run records.

    Passing ``price_in``/``price_out`` (USD per 1M tokens) recomputes cost from the
    recorded token counts, so calls made before prices were configured still count.
    """
    rows = list(records)
    if not rows:
        return {"calls": 0}

    def pick(key: str) -> list[float]:
        return [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]

    latencies = pick("latency_ms")
    prompt = pick("prompt_tokens")
    completion = pick("completion_tokens")
    if price_in is not None and price_out is not None:
        billed = [
            (r.get("prompt_tokens") or 0) / 1_000_000 * price_in
            + (r.get("completion_tokens") or 0) / 1_000_000 * price_out
            for r in rows
            if r.get("prompt_tokens") is not None or r.get("completion_tokens") is not None
        ]
        costs = billed
    else:
        costs = pick("cost_usd")

    by_mode: dict[str, int] = {}
    by_model: dict[str, int] = {}
    errors: dict[str, int] = {}
    for row in rows:
        by_mode[str(row.get("mode", "unknown"))] = by_mode.get(str(row.get("mode", "unknown")), 0) + 1
        by_model[str(row.get("model", "unknown"))] = by_model.get(str(row.get("model", "unknown")), 0) + 1
        if not row.get("ok", True):
            code = str(row.get("error_code", "UNKNOWN"))
            errors[code] = errors.get(code, 0) + 1

    return {
        "calls": len(rows),
        "ok": sum(1 for r in rows if r.get("ok", True)),
        "failed": sum(1 for r in rows if not r.get("ok", True)),
        "by_mode": by_mode,
        "by_model": by_model,
        "error_codes": errors,
        "prompt_tokens": int(sum(prompt)) if prompt else 0,
        "completion_tokens": int(sum(completion)) if completion else 0,
        "total_tokens": int(sum(prompt) + sum(completion)) if (prompt or completion) else 0,
        "cost_usd": round(sum(costs), 4) if costs else None,
        "cost_missing_calls": len(rows) - len(costs),
        "latency_ms_mean": round(statistics.fmean(latencies)) if latencies else None,
        "latency_ms_p50": round(_percentile(latencies, 0.50)) if latencies else None,
        "latency_ms_p95": round(_percentile(latencies, 0.95)) if latencies else None,
    }
