import json
from dataclasses import replace

import pytest

import evaluation_adapter
import integration
from backend import DATA_DIR, Request, development_cases
from evaluation import evaluate_systems as protocol
from integration import IntegratedBackend, ReplayClient, decision_engine
from reco.config import Config
from reco.pipeline import Recognizer


DEVELOPMENT = list(development_cases().values())
FORMAL = protocol.manifest()
OBSERVATIONS = {
    record["case_id"]: record["observation"]
    for line in (protocol.DATA / "scripted_observations.jsonl").read_text(encoding="utf-8").splitlines()
    for record in (json.loads(line),)
}
CANDIDATES = {
    "beverage_bottle": ("plastic_beverage_bottle", "glass_beverage_bottle"),
    "drink_cup": ("disposable_plastic_cup",),
    "snack_packet": ("foil_lined_snack_packet",),
    "metal_can": ("metal_food_can", "aluminium_beverage_can"),
    "container": ("plastic_beverage_bottle", "glass_beverage_bottle", "glass_food_jar"),
}


@pytest.mark.parametrize("case", DEVELOPMENT, ids=[row["case_id"] for row in DEVELOPMENT])
def test_development_fixture_through_page_contract(case):
    backend = IntegratedBackend(fixture=True)
    request = Request((DATA_DIR / case["image_path"]).read_bytes(), "image/jpeg", demo_case=case["case_id"])
    response = backend.respond(request)
    if case["expected_action"] == "clarify_item":
        assert response.status == "question"
        assert response.recognition is not None
        answer = "Glass" if case["case_id"] == "DEV-17" else "Paper"
        reply = replace(request, answers=((response.question, answer),), recognition=response.recognition)
        expected = "glass_beverage_bottle" if answer == "Glass" else None
        assert backend.respond(reply).item_id == expected
        assert backend.respond(reply).status == ("ready" if expected else "unsupported")
    elif case["expected_action"] == "give_advice":
        assert response.status == "ready"
        assert response.item_id == case["expected_item_id"]
        assert response.route_id == case["expected_route_id"]
        assert response.advice == case["expected_response"]
    else:
        assert response.status == "unsupported"
        assert response.fallback_key == "unsupported_item"


def test_live_adapter_reuses_the_recognition_after_an_answer(monkeypatch):
    client = ReplayClient(candidates=CANDIDATES["beverage_bottle"])
    rec = Recognizer(Config(provider="fixture", log_path="runs/test_fixture.jsonl"), client=client)
    monkeypatch.setattr(integration, "live_recognizer", lambda: rec)
    live = IntegratedBackend()
    request = Request((DATA_DIR / "development_photos/DEV-17.jpg").read_bytes(), "image/jpeg")
    first = live.respond(request)
    assert first.status == "question"
    monkeypatch.setattr(integration, "live_recognizer", lambda: pytest.fail("Recognition was called again"))
    question = replace(request, recognition=first.recognition, answers=((first.question, "Not sure"),))
    second = live.respond(question)
    assert second.status == "question" and second.question != first.question
    terminal = replace(question, answers=question.answers + ((second.question, "Not sure"),))
    assert live.respond(terminal).fallback_key == "unresolved_item"
    corrected = replace(terminal, corrected_item_id="glass_beverage_bottle")
    assert live.respond(corrected).item_id == "glass_beverage_bottle"


@pytest.mark.parametrize(("answer", "expected_item_id"), [
    ("Plastic", "plastic_beverage_bottle"),
    ("Glass", "glass_beverage_bottle"),
])
def test_uncertain_named_bottle_waits_for_user_confirmation(monkeypatch, answer, expected_item_id):
    client = ReplayClient(name="Plastic beverage bottle", candidates=CANDIDATES["beverage_bottle"])
    recognizer = Recognizer(Config(provider="fixture", log_path="runs/test_fixture.jsonl"), client=client)
    monkeypatch.setattr(integration, "live_recognizer", lambda: recognizer)
    backend = IntegratedBackend()
    request = Request((DATA_DIR / "development_photos/DEV-17.jpg").read_bytes(), "image/jpeg")

    first = backend.respond(request)
    assert first.status == "question"
    assert first.question_key == "material"
    assert first.recognition.item_id_candidates == list(CANDIDATES["beverage_bottle"])

    monkeypatch.setattr(integration, "live_recognizer", lambda: pytest.fail("Recognition was called again"))
    reply = replace(request, recognition=first.recognition, answers=((first.question, answer),))
    final = backend.respond(reply)
    assert final.status == "ready"
    assert final.item_id == expected_item_id
    assert final.confirmed_by == "user_answer"
    assert final.advice == decision_engine().items[expected_item_id]["disposal_advice"]


@pytest.mark.parametrize("case", FORMAL, ids=[row["case_id"] for row in FORMAL])
def test_e_scripted_observation_through_integrated_evaluation_adapter(case, monkeypatch):
    observation = OBSERVATIONS[case["case_id"]]
    kind = observation["kind"]
    catalogue = decision_engine().catalogue
    item_id = observation.get("confirmed_item_id", "unknown")
    if item_id not in catalogue.items and item_id != "unknown":
        item_id = "out_of_scope"
    client = ReplayClient(item_id=item_id, candidates=CANDIDATES.get(kind, ()), usable=kind != "no_clear_object")
    recognizer = Recognizer(Config(provider="fixture", log_path="runs/test_fixture.jsonl"), client=client)
    monkeypatch.setattr(evaluation_adapter, "_recognizer", lambda: recognizer)
    monkeypatch.setattr(evaluation_adapter, "_previous", None)
    path = protocol.ROOT / case["image_path"]
    first = protocol.invoke(evaluation_adapter.predict, "improved", path, [])
    assert first["status"] == "ok"
    assert first["action"] == case["expected_initial_action"]
    assert first["question_key"] == case["question_key_1"]
    calls, history, stop_reason = protocol.interactive(evaluation_adapter.predict, first, path, case)
    assert not stop_reason
    assert len(history) == sum(bool(case[f"question_key_{n}"]) for n in (1, 2))
    final = calls[-1]
    assert final["status"] == "ok"
    assert final["action"] == case["expected_final_action"]
    assert final["item_id"] == case["expected_final_item_id"]
    assert final["advice"] == case["expected_final_advice"]
