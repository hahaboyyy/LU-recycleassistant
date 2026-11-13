import json

import pytest

from reco.parsing import JSONExtractError, SchemaError, extract_json_object, parse_baseline, parse_result, strip_confidence


VALID = {
    "identification": {"name_en": "plastic bottle", "category_en": "beverage container"},
    "materials": [{"name_en": "PET plastic", "basis": "observed"}],
    "visible_state": {"is_empty": "yes", "has_residue": "unknown"},
    "image_quality": {"usable": True},
}


def test_plain_json():
    data = extract_json_object(json.dumps(VALID))
    assert data["identification"]["name_en"] == "plastic bottle"


def test_fenced_json():
    text = "```json\n" + json.dumps(VALID) + "\n```"
    assert extract_json_object(text)["materials"][0]["name_en"] == "PET plastic"


def test_prose_around_json_with_braces_in_strings():
    text = (
        "Here you go: "
        + json.dumps({"identification": {"name_en": "bottle {with braces}"}})
        + " hope that helps"
    )
    data = extract_json_object(text)
    assert data["identification"]["name_en"] == "bottle {with braces}"


def test_trailing_commas_repaired():
    broken = '{"identification": {"name_en": "cup",},}'
    assert extract_json_object(broken)["identification"]["name_en"] == "cup"


def test_no_json_raises():
    with pytest.raises(JSONExtractError):
        extract_json_object("Sure, it looks like a bottle.")
    with pytest.raises(JSONExtractError):
        extract_json_object("")


def test_confidence_keys_are_stripped():
    payload = {
        **VALID,
        "confidence": 0.97,
        "identification": {**VALID["identification"], "confidence": 0.9},
        "materials": [{**VALID["materials"][0], "probability": 0.8}],
    }
    cleaned, dropped = strip_confidence(payload)
    assert dropped == 3
    assert "confidence" not in cleaned
    assert "probability" not in cleaned["materials"][0]


def test_parse_result_ok_and_unknowns_derived():
    result, dropped = parse_result(json.dumps(VALID))
    assert result.identification.name_en == "plastic bottle"
    # has_residue was "unknown"; is_liquid etc. defaulted to unknown as well
    assert "has_residue" in result.unknown_conditions
    assert "is_damaged" in result.unknown_conditions
    assert "material" not in result.unknown_conditions


def test_parse_result_missing_required_field():
    with pytest.raises(SchemaError) as info:
        parse_result(json.dumps({"visible_state": {"is_empty": "yes"}}))
    assert "identification" in str(info.value)


def test_chinese_and_bool_values_coerced():
    payload = {
        "identification": {"name_en": "bottle"},
        "visible_state": {"is_empty": True, "has_liquid": None, "is_clean": "不确定"},
    }
    result, _ = parse_result(json.dumps(payload, ensure_ascii=False))
    assert result.visible_state.is_empty == "yes"
    assert result.visible_state.has_liquid == "unknown"
    assert result.visible_state.is_clean == "unknown"


def test_baseline_json_and_freetext():
    j = parse_baseline(json.dumps({"identification": "can", "disposal_advice": "Recycle it."}))
    assert j.identification == "can" and j.disposal_advice == "Recycle it."

    free = parse_baseline("Plastic bottle\nRinse and drop it in the plastic bin.")
    assert free.identification == "Plastic bottle"
    assert "Rinse" in free.disposal_advice
