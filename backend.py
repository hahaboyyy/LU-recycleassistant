"""Role D backend contract and deterministic development fixtures."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from reco.schema import RecognitionResult


DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Request:
    image: bytes
    mime_type: str
    corrected_item_id: str | None = None
    answers: tuple[tuple[str, str], ...] = ()
    demo_case: str | None = None
    recognition: RecognitionResult | None = None


@dataclass(frozen=True)
class Response:
    status: str
    item_id: str | None = None
    question: str | None = None
    options: tuple[str, ...] = ()
    recognition: RecognitionResult | None = None
    route_id: str = ""
    source_ids: tuple[str, ...] = ()
    fallback_key: str = ""
    advice: str = ""
    identification: str = ""
    confirmed_by: str = ""
    question_key: str = ""


class Backend(Protocol):
    def respond(self, request: Request) -> Response: ...


def load_rules() -> dict:
    with (DATA_DIR / "rules_v1.json").open(encoding="utf-8-sig") as source:
        return json.load(source)


def development_cases() -> dict[str, dict[str, str]]:
    with (DATA_DIR / "development_cases.csv").open(
        encoding="utf-8-sig", newline=""
    ) as source:
        return {row["case_id"]: row for row in csv.DictReader(source)}


def demo_cases() -> dict[str, str]:
    """List explicit sample scenarios; selection is never image inference."""
    names = {rule["item_id"]: rule["item_name"] for rule in load_rules()["rules"]}
    labels = {
        "DEV-17": "Beverage bottle: confirm the material",
        "DEV-18": "Disposable cup: confirm the material",
        "DEV-19": "Shoe: outside the guide",
        "DEV-20": "Aerosol: outside the guide",
    }
    cases = {
        case_id: labels.get(case_id, names.get(row["expected_item_id"], case_id))
        for case_id, row in development_cases().items()
    }
    cases.update({
        "UNCLEAR": "Simulated unclear photo",
        "TWO_QUESTIONS": "Simulated two-question bottle clarification",
        "ERROR": "Simulated backend failure",
        "TIMEOUT": "Simulated backend timeout",
    })
    return cases


def _answer(request: Request, question: str) -> str | None:
    for asked, answer in reversed(request.answers):
        if asked == question:
            return answer.strip().casefold()
    return None


class DemoBackend:
    """A fixture adapter: it does not inspect or send image bytes."""

    def __init__(self, timeout_seconds: float = 8):
        self.timeout_seconds = timeout_seconds
        self._items = {rule["item_id"] for rule in load_rules()["rules"]}
        self._cases = development_cases()

    def _ready(self, item_id: str) -> Response:
        if item_id in self._items:
            return Response("ready", item_id=item_id)
        return Response("unsupported")

    def _material(self, request: Request, case_id: str) -> Response:
        question = self._cases[case_id]["expected_response"]
        answer = _answer(request, question)
        if case_id == "DEV-17":
            options = ("Plastic", "Glass", "Not sure")
            if answer == "plastic":
                return self._ready("plastic_beverage_bottle")
            if answer == "glass":
                return self._ready("glass_beverage_bottle")
        else:
            options = ("Rigid plastic", "Paper", "Not sure")
            if answer == "rigid plastic":
                return self._ready("disposable_plastic_cup")
            if answer == "paper":
                return Response("unsupported")
        return Response("question", question=question, options=options)

    def respond(self, request: Request) -> Response:
        if request.corrected_item_id is not None:
            return self._ready(request.corrected_item_id)

        case_id = request.demo_case
        if case_id == "ERROR":
            raise RuntimeError("Simulated demo backend failure.")
        if case_id == "TIMEOUT":
            time.sleep(max(0, self.timeout_seconds) + 0.75)
            return Response("unclear")
        if case_id == "TWO_QUESTIONS":
            question = "Is the main item a beverage bottle?"
            answer = _answer(request, question)
            if answer == "yes":
                return self._material(request, "DEV-17")
            if answer == "no":
                return Response("unsupported")
            return Response("question", question=question, options=("Yes", "No", "Not sure"))

        row = self._cases.get(case_id) if case_id is not None else None
        if row is None:
            # Includes UNCLEAR and uploads without an explicit fixture choice.
            return Response("unclear")
        if row["expected_action"] == "give_advice":
            return self._ready(row["expected_item_id"])
        if row["expected_action"] == "out_of_scope":
            return Response("unsupported")
        if row["expected_action"] == "clarify_item" and case_id in ("DEV-17", "DEV-18"):
            return self._material(request, case_id)
        return Response("unclear")


def load_live_backend(spec: str) -> Backend:
    """Load a no-argument factory named by trusted operator configuration."""
    module_name, separator, factory_name = spec.strip().partition(":")
    if not separator or not factory_name.isidentifier() or not all(
        part.isidentifier() for part in module_name.split(".")
    ):
        raise ValueError("Use module:factory for RECYCLE_D_BACKEND.")
    factory = getattr(import_module(module_name), factory_name, None)
    if not callable(factory):
        raise TypeError("The configured backend factory is not callable.")
    backend = factory()
    if not callable(getattr(backend, "respond", None)):
        raise TypeError("The configured backend must provide respond(request).")
    return backend
