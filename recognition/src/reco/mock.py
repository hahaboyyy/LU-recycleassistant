"""Deterministic stand-in provider.

Lets module D build the UI, module E dry-run the harness and pytest run the
whole pipeline before any API key, budget or network exists. It speaks the
same ``chat(messages)`` interface as the real client.

Scenarios mirror Role A's three development outcomes: a confirmed catalogue
item, an ambiguous item (two plausible ids) and an item outside the catalogue.
"""

from __future__ import annotations

import json
from typing import Any

from .client import EmptyResponseError, LLMError, LLMResponse

SCENARIOS: dict[str, dict[str, Any]] = {
    "bottle": {
        "identification": {
            "name_en": "Plastic beverage bottle",
            "category_en": "beverage container",
            "alternatives_en": [],
        },
        "item_id": "plastic_beverage_bottle",
        "item_id_candidates": [],
        "materials": [
            {
                "name_en": "Plastic",
                "role": "primary",
                "basis": "observed",
                "evidence": "transparent body, PET mark on base",
            }
        ],
        "visible_state": {
            "is_empty": "yes",
            "has_liquid": "no",
            "has_residue": "unknown",
            "is_clean": "unknown",
            "is_damaged": "no",
            "has_multiple_components": "no",
        },
        "other_unknowns": ["cap is still attached"],
        "image_quality": {"usable": True, "main_object_visible": "yes", "issues": []},
        "notes_en": "Label still attached, bottle is crushed slightly at the base.",
    },
    "takeaway": {
        "identification": {
            "name_en": "Disposable plastic cup",
            "category_en": "food packaging",
            "alternatives_en": [],
        },
        "item_id": "disposable_plastic_cup",
        "item_id_candidates": [],
        "materials": [
            {"name_en": "Rigid plastic", "role": "primary", "basis": "suspected", "evidence": "glossy cup wall"},
            {"name_en": "Plastic film", "role": "component", "basis": "suspected", "evidence": "laminated lid"},
        ],
        "visible_state": {
            "is_empty": "yes",
            "has_liquid": "no",
            "has_residue": "yes",
            "is_clean": "no",
            "is_damaged": "no",
            "has_multiple_components": "yes",
        },
        "other_unknowns": [],
        "image_quality": {"usable": True, "main_object_visible": "yes", "issues": []},
        "notes_en": "Visible residue inside; lid still attached.",
    },
    "ambiguous": {
        "identification": {
            "name_en": "clear beverage bottle",
            "category_en": "beverage container",
            "alternatives_en": ["glass bottle", "plastic bottle"],
        },
        "item_id": "unknown",
        "item_id_candidates": ["plastic_beverage_bottle", "glass_beverage_bottle"],
        "materials": [
            {"name_en": "Glass", "role": "primary", "basis": "suspected", "evidence": "thick base, no mould seam visible"},
            {"name_en": "Plastic", "role": "primary", "basis": "suspected", "evidence": "clear wall, cannot see a material mark"},
        ],
        "visible_state": {
            "is_empty": "yes",
            "has_liquid": "no",
            "has_residue": "no",
            "is_clean": "unknown",
            "is_damaged": "no",
            "has_multiple_components": "no",
        },
        "other_unknowns": ["material mark not visible"],
        "image_quality": {"usable": True, "main_object_visible": "yes", "issues": []},
        "notes_en": "Clear bottle; material cannot be confirmed from the photo.",
    },
    "out_of_scope": {
        "identification": {
            "name_en": "power bank",
            "category_en": "electronic device",
            "alternatives_en": ["battery pack"],
        },
        "item_id": "out_of_scope",
        "item_id_candidates": [],
        "materials": [
            {"name_en": "Metal", "role": "component", "basis": "suspected", "evidence": "aluminium casing"},
            {"name_en": "Plastic", "role": "component", "basis": "suspected", "evidence": "moulded shell"},
        ],
        "visible_state": {
            "is_empty": "unknown",
            "has_liquid": "no",
            "has_residue": "no",
            "is_clean": "yes",
            "is_damaged": "no",
            "has_multiple_components": "yes",
        },
        "other_unknowns": [],
        "image_quality": {"usable": True, "main_object_visible": "yes", "issues": []},
        "notes_en": "Electronic item; not part of the campus item catalogue.",
    },
    "bad_photo": {
        "identification": {"name_en": "unknown object", "category_en": "", "alternatives_en": []},
        "item_id": "unknown",
        "item_id_candidates": [],
        "materials": [],
        "visible_state": {
            "is_empty": "unknown",
            "has_liquid": "unknown",
            "has_residue": "unknown",
            "is_clean": "unknown",
            "is_damaged": "unknown",
            "has_multiple_components": "unknown",
        },
        "other_unknowns": [],
        "image_quality": {
            "usable": False,
            "main_object_visible": "no",
            "issues": ["blurry", "too_dark"],
        },
        "notes_en": "",
    },
}

#: Replies that should trigger the repair path.
BAD_REPLIES = {
    "prose": "Sure! Looking at the image, this appears to be a plastic bottle. "
             "It looks like PET plastic and would go into a recyclable bin.",
    "fenced": "```json\n" + json.dumps(SCENARIOS["bottle"], ensure_ascii=False) + "\n```",
    "trailing_comma": json.dumps(SCENARIOS["bottle"]).replace('"no"', '"no",', 3),
    "empty": "",
}


class MockClient:
    """``fail_first`` returns a broken reply N times before behaving."""

    def __init__(self, scenario: str = "bottle", fail_first: int = 0, fail_with: str = "prose",
                 calls: int = 0) -> None:
        self.scenario = scenario
        self.fail_first = fail_first
        self.fail_with = fail_with
        self.calls = calls
        self.model = f"mock-{scenario}"

    def chat(self, messages: list[dict], *, max_tokens: int | None = None) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.fail_first:
            text = BAD_REPLIES[self.fail_with]
            if not text:
                raise EmptyResponseError("mock empty reply")
            return self._wrap(text)

        scene = SCENARIOS.get(self.scenario)
        if scene is None:
            raise LLMError(f"unknown mock scenario {self.scenario!r}")
        if _is_baseline(messages):
            payload = {
                "identification": "plastic bottle (single-use)",
                "disposal_advice": "Empty and rinse the bottle, then put it in the plastic "
                                   "recycling bin on campus. Cap can stay on.",
                "notes_en": "",
            }
        else:
            payload = scene
        return self._wrap(json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _wrap(text: str) -> LLMResponse:
        return LLMResponse(
            text=text,
            model="mock-vision-1",
            latency_ms=12,
            prompt_tokens=1180,
            completion_tokens=160,
            finish_reason="stop",
            attempts=1,
        )


def _is_baseline(messages: list[dict]) -> bool:
    for msg in messages:
        if msg.get("role") == "system" and "answer directly" in str(msg.get("content", "")):
            return True
    return False
