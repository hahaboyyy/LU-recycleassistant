"""Turn a model reply into a validated object: fences, prose, trailing commas,
stray confidence keys, then Pydantic validation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from .schema import BaselineResult, RecognitionResult

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_CONFIDENCE_KEYS = {"confidence", "score", "probability", "likelihood", "certainty", "prob"}
_CONFIDENCE_SUBSTR = ("confidence", "probability")


class JSONExtractError(Exception):
    """No JSON object could be recovered from the text."""


class SchemaError(Exception):
    """JSON was found but does not satisfy the contract."""

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


def extract_json_object(text: str) -> dict:
    if not text or not text.strip():
        raise JSONExtractError("empty response")

    candidates: list[str] = [text.strip()]
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    last_error = "no '{' found"
    for candidate in candidates:
        for variant in (candidate, candidate.replace("，", ",")):
            try:
                data = json.loads(variant)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                last_error = str(exc)
            stripped = _balanced_object(variant)
            if stripped is None:
                continue
            for attempt in (stripped, _TRAILING_COMMA_RE.sub(r"\1", stripped)):
                try:
                    data = json.loads(attempt)
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError as exc:
                    last_error = str(exc)
    raise JSONExtractError(f"no valid JSON object in reply ({last_error})")


def _balanced_object(text: str) -> str | None:
    """Extract the first balanced {...}, ignoring braces inside strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def strip_confidence(obj: Any) -> tuple[Any, int]:
    """Remove self-reported certainty keys anywhere in the structure."""
    dropped = 0
    if isinstance(obj, dict):
        clean: dict[str, Any] = {}
        for key, value in obj.items():
            low = str(key).lower()
            if low in _CONFIDENCE_KEYS or any(s in low for s in _CONFIDENCE_SUBSTR):
                dropped += 1
                continue
            cleaned, sub = strip_confidence(value)
            dropped += sub
            clean[key] = cleaned
        return clean, dropped
    if isinstance(obj, list):
        out = []
        for item in obj:
            cleaned, sub = strip_confidence(item)
            dropped += sub
            out.append(cleaned)
        return out, dropped
    return obj, dropped


def parse_result(text: str) -> tuple[RecognitionResult, int]:
    data = extract_json_object(text)
    data, dropped = strip_confidence(data)
    try:
        return RecognitionResult.model_validate(data), dropped
    except ValidationError as exc:
        issues = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        ]
        raise SchemaError("reply does not match the recognition contract: " + "; ".join(issues), issues) from exc


def parse_baseline(text: str) -> BaselineResult:
    try:
        data = extract_json_object(text)
    except JSONExtractError:
        data = {}
    identification = str(data.get("identification") or "").strip()
    advice = str(data.get("disposal_advice") or "").strip()
    if not identification and not advice:
        # Free-text fallback: first line is the identification, rest is the advice.
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        identification = lines[0] if lines else "unknown"
        advice = " ".join(lines[1:]) if len(lines) > 1 else ""
    return BaselineResult(
        identification=identification or "unknown",
        disposal_advice=advice,
        notes_en=str(data.get("notes_en") or "").strip(),
        raw_text=text,
    )
