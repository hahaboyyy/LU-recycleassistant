"""Adapter contract tests (no network): mapping B's outcomes onto E's five actions."""

import reco.adapter as adapter
from reco.schema import BaselineResult, RecognitionResult, Trace


def _res(**kw):
    base = {"identification": {"name_en": "Plastic beverage bottle"}, "catalogue_status": "matched"}
    base.update(kw)
    return RecognitionResult.model_validate(base)


def test_action_mapping_covers_all_five_labels():
    assert adapter.action_for(_res(catalogue_status="matched")) == "give_advice"
    assert adapter.action_for(_res(catalogue_status="ambiguous", item_id="unknown")) == "clarify_item"
    assert adapter.action_for(_res(catalogue_status="out_of_scope", item_id="out_of_scope")) == "out_of_scope"
    assert adapter.action_for(_res(catalogue_status="unresolved")) == "unresolved_item"
    bad = _res(catalogue_status="unresolved", image_quality={"usable": False, "main_object_visible": "no"})
    assert adapter.action_for(bad) == "no_clear_object"


def test_question_key_vocabulary():
    assert adapter.question_key_for(_res(catalogue_status="ambiguous", item_id_candidates=["foil_lined_snack_packet"])) == "lining"
    assert (
        adapter.question_key_for(
            _res(catalogue_status="ambiguous", item_id_candidates=["metal_food_can", "aluminium_beverage_can"])
        )
        == "package_type"
    )
    assert (
        adapter.question_key_for(
            _res(catalogue_status="ambiguous", item_id_candidates=["plastic_beverage_bottle", "glass_beverage_bottle"])
        )
        == "material"
    )
    for key in ("material", "lining", "package_type", "item_label"):
        assert adapter.QUESTION_TEXT[key]


class _FakeRec:
    def __init__(self, result=None, baseline=None):
        self._result = result
        self._baseline = baseline
        self.calls = []

    def recognize(self, image, *, note="", clarification=""):
        self.calls.append({"image": image, "clarification": clarification})
        return self._result

    def baseline(self, image, *, note=""):
        self.calls.append({"image": image, "clarification": None})
        return self._baseline


def test_predict_improved_matched_returns_advice_from_rules():
    result = _res(item_id="plastic_beverage_bottle", catalogue_status="matched", catalogue_item_name_en="Plastic beverage bottle")
    result.trace = Trace(run_id="r", created_at="t", provider="mock", model="m", prompt_tokens=10, completion_tokens=5)
    fake = _FakeRec(result=result)
    old = adapter._recognizer
    adapter._recognizer = fake
    try:
        out = adapter.predict(mode="improved", image_path="x.jpg", history=[])
    finally:
        adapter._recognizer = old
    assert out["action"] == "give_advice"
    assert out["item_id"] == "plastic_beverage_bottle"
    assert "rinse" in out["advice"].lower()
    assert out["input_tokens"] == 10


def test_predict_passes_clarification_answer():
    result = _res(item_id="glass_beverage_bottle", catalogue_status="matched")
    fake = _FakeRec(result=result)
    old = adapter._recognizer
    adapter._recognizer = fake
    try:
        adapter.predict(
            mode="improved",
            image_path="x.jpg",
            history=[{"question": "What material?", "answer": "It is a glass bottle."}],
        )
    finally:
        adapter._recognizer = old
    assert fake.calls[0]["clarification"] == "It is a glass bottle."


def test_predict_baseline_always_answers():
    base = BaselineResult(identification="plastic bottle", disposal_advice="Recycle it.")
    base.trace = Trace(run_id="r", created_at="t", provider="mock", model="m")
    fake = _FakeRec(baseline=base)
    old = adapter._recognizer
    adapter._recognizer = fake
    try:
        out = adapter.predict(mode="baseline", image_path="x.jpg", history=[])
    finally:
        adapter._recognizer = old
    assert out["action"] == "give_advice"
    assert out["question"] == ""


def test_rules_file_matches_role_a_checksum():
    import hashlib

    assert hashlib.sha256(adapter.RULES_PATH.read_bytes()).hexdigest() == (
        "0481fe079e6a7b093ebc62f8e5bed68108ba3aa3f70ec8b7e70ec4db7e96dc75"
    )


def test_non_advice_actions_still_carry_user_facing_text():
    """E's invoke() requires advice text for every action, not only give_advice."""
    for status, expected in (("out_of_scope", "outside"), ("ambiguous", ""), ("unresolved", "could not")):
        result = _res(catalogue_status=status, item_id="unknown")
        fake = _FakeRec(result=result)
        old = adapter._recognizer
        adapter._recognizer = fake
        try:
            out = adapter.predict(mode="improved", image_path="x.jpg", history=[])
        finally:
            adapter._recognizer = old
        if expected:
            assert out["advice"], status
            assert expected in out["advice"].lower(), (status, out["advice"])
        else:
            assert out["advice"] == ""
