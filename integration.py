"""Shared Role B recognition and decision service for the page and evaluation."""

from __future__ import annotations

import json
from dataclasses import replace
from functools import cache

from backend import DATA_DIR, DemoBackend, Request, Response, development_cases
from decision import DecisionEngine
from reco.catalog import load_catalogue
from reco.client import LLMResponse
from reco.config import Config, load_config
from reco.pipeline import Recognizer


@cache
def decision_engine() -> DecisionEngine:
    return DecisionEngine(load_catalogue(DATA_DIR / "supported_items.csv"))


class ReplayClient:
    """Return a scripted provider response for the supplied development scenario."""

    def __init__(self, *, item_id="unknown", candidates=(), usable=True, name="Demo observation"):
        self.result = {
            "identification": {"name_en": name},
            "item_id": item_id,
            "item_id_candidates": candidates,
            "image_quality": {"usable": usable, "main_object_visible": "yes" if usable else "no"},
        }

    def chat(self, messages):
        return LLMResponse(text=json.dumps(self.result), model="fixture", latency_ms=0,
                           prompt_tokens=None, completion_tokens=None, finish_reason="stop", attempts=1)


def live_recognizer() -> Recognizer:
    cfg = load_config()
    if not cfg.api_key.strip():
        raise ValueError("Configure a vision API key before starting live recognition.")
    if not cfg.model.strip() or not cfg.base_url.strip():
        raise ValueError("Configure the vision API endpoint and model before starting live recognition.")
    # Streamlit can detach an overdue job. Limit provider retries and read time independently.
    cfg = replace(cfg, timeout_s=min(30.0, max(1.0, cfg.timeout_s)),
                  max_retries=min(1, max(0, cfg.max_retries)))
    return Recognizer(cfg, catalogue=decision_engine().catalogue)


class IntegratedBackend:
    def __init__(self, *, fixture=False, timeout=8.0):
        self.fixture = fixture
        self.timeout = timeout

    def _fixture_recognizer(self, case_id: str | None) -> Recognizer:
        row = development_cases().get(case_id, {})
        if case_id in {"DEV-17", "TWO_QUESTIONS"}:
            client = ReplayClient(candidates=("plastic_beverage_bottle", "glass_beverage_bottle"))
        elif case_id == "DEV-18":
            client = ReplayClient(candidates=("disposable_plastic_cup",))
        elif row.get("expected_action") == "out_of_scope":
            client = ReplayClient(item_id="out_of_scope", name=row["photo_target"])
        elif row.get("expected_action") == "give_advice":
            client = ReplayClient(item_id=row["expected_item_id"])
        else:
            client = ReplayClient(usable=False)
        cfg = Config(provider="fixture", model="fixture", log_path="runs/fixture_recognition.jsonl")
        return Recognizer(cfg, client=client, catalogue=decision_engine().catalogue)

    def respond(self, request: Request) -> Response:
        if self.fixture and request.demo_case in {"ERROR", "TIMEOUT"} and not request.corrected_item_id:
            return DemoBackend(self.timeout).respond(request)
        record = request.recognition
        if record is None and not request.corrected_item_id:
            recognizer = self._fixture_recognizer(request.demo_case) if self.fixture else live_recognizer()
            record = recognizer.recognize(request.image)
        result = decision_engine().decide(record, request.answers, request.corrected_item_id)
        status = {"advice": "ready", "clarify": "question", "retake": "unclear",
                  "out_of_scope": "unsupported", "unresolved": "unresolved"}[result.outcome]
        return Response(
            status, item_id=result.item_id or None, question=result.question_en or None,
            options=result.options, recognition=record if status == "question" else None,
            route_id=result.route_id, source_ids=result.source_ids, fallback_key=result.fallback_key,
            advice=result.disposal_advice,
            identification=result.identification, confirmed_by=result.confirmed_by,
            question_key=result.question_key,
        )


def create_live_backend() -> IntegratedBackend:
    return IntegratedBackend()
