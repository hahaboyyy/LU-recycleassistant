"""Adapter for Role E's ``evaluate_systems.py``.

E's harness calls ``predict(mode=..., image_path=..., history=...)`` and expects a
flat dict of strings:

    action, item_id, identification, advice, question, question_key
    (+ optional input_tokens / output_tokens)

Two arms:

* ``baseline`` -- direct answer, same model, no catalogue, no rule lookup.
  It always answers, which is exactly what the baseline is supposed to do.
* ``improved`` -- module B recognition, then a **temporary** lookup of Role A's
  fixed advice from ``data/rules_v1.json``. That lookup belongs to module C; it
  lives here only so E can run both arms end to end. When C ships its module,
  replace ``_advice_for`` with a call into it and delete the JSON read.

Clarification turns: when ``history`` contains the user's answer, it is passed to
the recognizer as text so the second call can resolve the attribute that was not
visible in the photo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .pipeline import Recognizer
from .schema import RecognitionResult
from .catalog import default_path

RULES_PATH = default_path().with_name("rules_v1.json")

QUESTION_TEXT = {
    "material": "What material is the main item made of?",
    "lining": "Does the inside of the snack packet have a metallic lining?",
    "package_type": "Was this can used for food or for a beverage?",
    "item_label": "What does the label or marking on the item say?",
}

_rules_cache: dict[str, Any] | None = None
_recognizer: Recognizer | None = None


def _rules() -> dict[str, Any]:
    global _rules_cache
    if _rules_cache is None:
        path = Path(os.environ.get("RECO_RULES", str(RULES_PATH)))
        _rules_cache = json.loads(path.read_text(encoding="utf-8"))
    return _rules_cache


#: E's harness requires a user-facing text for EVERY action, not only give_advice.
FALLBACK_KEYS = {
    "out_of_scope": "unsupported_item",
    "no_clear_object": "no_clear_object",
    "unresolved_item": "unresolved_item",
}


def _fallback_text(action: str) -> str:
    return str(_rules().get(FALLBACK_KEYS.get(action, "unresolved_item"), ""))


def _advice_for(item_id: str) -> str:
    """Temporary stand-in for module C: A's fixed advice, keyed by item_id."""
    rules = _rules()
    for entry in rules.get("rules", []):
        if entry.get("item_id") == item_id:
            return str(entry.get("disposal_advice", ""))
    return str(rules.get("unsupported_item", ""))


def _recognizer_singleton() -> Recognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = Recognizer()
    return _recognizer


def action_for(result: RecognitionResult) -> str:
    """Map B's four outcomes onto E's five action labels."""
    if result.catalogue_status == "matched":
        return "give_advice"
    if result.catalogue_status == "ambiguous":
        return "clarify_item"
    if result.catalogue_status == "out_of_scope":
        return "out_of_scope"
    return "no_clear_object" if result.needs_new_photo else "unresolved_item"


def question_key_for(result: RecognitionResult) -> str:
    """Pick the attribute that decides the match, using E's fixed vocabulary."""
    candidates = set(result.item_id_candidates)
    if "foil_lined_snack_packet" in candidates:
        return "lining"
    if candidates and candidates <= {"metal_food_can", "aluminium_beverage_can"}:
        return "package_type"
    return "material"


def predict(*, mode: str, image_path: str | Path, history: list[dict] | None = None) -> dict[str, Any]:
    rec = _recognizer_singleton()
    clarification = ""
    if history:
        clarification = str(history[-1].get("answer", ""))

    if mode == "baseline":
        base = rec.baseline(str(image_path))
        trace = base.trace
        return {
            "action": "give_advice",
            "item_id": "",
            "identification": base.identification,
            "advice": base.disposal_advice,
            "question": "",
            "question_key": "",
            "input_tokens": getattr(trace, "prompt_tokens", None),
            "output_tokens": getattr(trace, "completion_tokens", None),
        }

    result = rec.recognize(str(image_path), clarification=clarification)
    action = action_for(result)
    trace = result.trace
    key = question_key_for(result) if action == "clarify_item" else ""
    if action == "give_advice":
        advice = _advice_for(result.item_id)
    elif action == "clarify_item":
        advice = ""
    else:
        advice = _fallback_text(action)
    return {
        "action": action,
        "item_id": result.item_id if action == "give_advice" else "",
        "identification": result.display_name_en,
        "advice": advice,
        "question": QUESTION_TEXT.get(key, "") if key else "",
        "question_key": key,
        "input_tokens": getattr(trace, "prompt_tokens", None),
        "output_tokens": getattr(trace, "completion_tokens", None),
    }
