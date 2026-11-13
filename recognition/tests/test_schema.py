import json

from reco.prompts import OUTPUT_SKELETON
from reco.schema import (
    CONDITION_QUESTION,
    TRIFIELDS,
    BaselineResult,
    Identification,
    RecognitionResult,
    VisibleState,
)


def test_tristate_accepts_bool_null_and_synonyms():
    state = VisibleState(
        is_empty=True,
        has_liquid=None,
        has_residue="不确定",
        is_clean="NO",
        is_damaged=0,
        has_multiple_components="maybe",
    )
    assert state.is_empty == "yes"
    assert state.has_liquid == "unknown"
    assert state.has_residue == "unknown"
    assert state.is_clean == "no"
    assert state.is_damaged == "no"
    assert state.has_multiple_components == "unknown"


def _result(**kw):
    base = {"identification": {"name_en": "Plastic beverage bottle"}, "catalogue_status": "matched"}
    base.update(kw)
    return RecognitionResult.model_validate(base)


def test_unknown_conditions_are_computed_from_fields():
    res = _result(
        materials=[{"name_en": "Plastic"}],
        visible_state={"is_empty": "yes", "is_clean": "no"},
    )
    assert res.unknown_conditions == ["has_liquid", "has_residue", "is_damaged", "has_multiple_components"]
    assert res.follow_up_questions_en[0] == CONDITION_QUESTION["has_liquid"]
    assert res.needs_new_photo is False


def test_matched_item_removes_item_condition():
    assert "item" not in _result().unknown_conditions
    ambiguous = _result(catalogue_status="ambiguous", item_id="unknown", item_id_candidates=["glass_beverage_bottle"])
    assert "item" in ambiguous.unknown_conditions


def test_ambiguous_asks_a_question_but_does_not_need_a_new_photo():
    res = _result(
        catalogue_status="ambiguous",
        item_id="unknown",
        item_id_candidates=["plastic_beverage_bottle", "glass_beverage_bottle"],
    )
    assert res.needs_clarification is True
    assert res.needs_new_photo is False
    assert res.unknown_conditions[0] == "item"


def test_out_of_scope_is_not_a_question_and_not_a_retake():
    res = _result(
        catalogue_status="out_of_scope",
        item_id="out_of_scope",
        identification={"name_en": "power bank"},
    )
    assert res.needs_clarification is False
    assert res.needs_new_photo is False
    assert res.display_name_en == "power bank"


def test_no_material_marks_material_unknown():
    res = _result(materials=[])
    assert res.unknown_conditions[0] == "material"


def test_unusable_photo_needs_retake():
    res = _result(image_quality={"usable": False, "main_object_visible": "no", "issues": ["blurry", "too_dark"]})
    assert res.needs_new_photo is True
    assert "blurry" not in res.retake_hint_en  # slug replaced by plain wording
    assert "steady" in res.retake_hint_en and "brighter" in res.retake_hint_en


def test_display_name_prefers_catalogue_name():
    res = _result(
        identification={"name_en": "plastic water bottle"},
        catalogue_item_name_en="Plastic beverage bottle",
    )
    assert res.display_name_en == "Plastic beverage bottle"


def test_computed_fields_survive_dump():
    data = json.loads(_result().model_dump_json())
    for key in (
        "unknown_conditions",
        "follow_up_questions_en",
        "needs_new_photo",
        "needs_clarification",
        "display_name_en",
    ):
        assert key in data
    assert data["schema_version"] == "b-0.2"


def test_prompt_skeleton_matches_schema():
    skeleton = json.loads(OUTPUT_SKELETON)
    fields = set(RecognitionResult.model_fields)
    assert set(skeleton) <= fields, set(skeleton) - fields
    assert set(skeleton["visible_state"]) == set(TRIFIELDS)
    assert "item_id" in skeleton and "item_id_candidates" in skeleton


def test_no_confidence_field_in_contract():
    for model in (RecognitionResult, Identification, BaselineResult):
        assert not any("confidence" in name for name in model.model_fields)


def test_ambiguous_wins_over_needs_new_photo():
    """C checks needs_new_photo first; if ambiguous also set it, the clarify path dies."""
    res = _result(
        catalogue_status="ambiguous",
        item_id="unknown",
        item_id_candidates=["plastic_beverage_bottle", "glass_beverage_bottle"],
        image_quality={"usable": True, "main_object_visible": "no", "issues": []},
    )
    assert res.needs_new_photo is False
    assert res.needs_clarification is True
