import pytest

from integration import decision_engine
from reco.schema import RecognitionResult


def ambiguous(*candidates):
    return RecognitionResult(
        identification={"name_en": "Unconfirmed item"},
        catalogue_status="ambiguous", item_id_candidates=list(candidates),
    )


@pytest.mark.parametrize(("candidates", "answer", "outcome", "item_id"), [
    (("disposable_plastic_cup",), "It is a rigid plastic cup.", "advice", "disposable_plastic_cup"),
    (("disposable_plastic_cup",), "It is a paper cup.", "out_of_scope", ""),
    (("glass_food_jar", "glass_beverage_bottle"), "It is a glass jar used for food.", "advice", "glass_food_jar"),
    (("paper_tissue", "office_paper"), "Paper tissue", "advice", "paper_tissue"),
    (("paper_tissue", "office_paper"), "Office paper", "advice", "office_paper"),
])
def test_user_answer_resolves_the_actual_item(candidates, answer, outcome, item_id):
    engine = decision_engine()
    record = ambiguous(*candidates)
    first = engine.decide(record)
    assert first.outcome == "clarify"
    result = engine.decide(record, ((first.question_en, answer),))
    assert result.outcome == outcome
    assert result.item_id == item_id
    assert result.disposal_advice


@pytest.mark.parametrize("answer", [
    "It is not glass.",
    "I cannot tell if it is plastic or glass.",
    "I don't know if it is glass.",
    "Maybe plastic.",
])
def test_unknown_or_negated_material_is_not_confirmed_as_glass(answer):
    engine = decision_engine()
    record = ambiguous("plastic_beverage_bottle", "glass_beverage_bottle")
    first = engine.decide(record)
    result = engine.decide(record, ((first.question_en, answer),))
    assert result.outcome == "clarify"
    assert not result.item_id
    assert result.question_en != first.question_en


def test_generic_paper_does_not_confirm_tissue():
    engine = decision_engine()
    record = ambiguous("paper_tissue", "office_paper")
    first = engine.decide(record)
    assert first.options == ("Paper tissue", "Office paper", "Not sure")
    result = engine.decide(record, ((first.question_en, "paper"),))
    assert result.outcome == "unresolved"
    assert not result.item_id


def test_interleaved_photo_histories_and_retries_remain_independent():
    engine = decision_engine()
    bottle = ambiguous("plastic_beverage_bottle", "glass_beverage_bottle")
    cup = ambiguous("disposable_plastic_cup")
    bottle_question = engine.decide(bottle)
    cup_question = engine.decide(cup)
    bottle_answer = ((bottle_question.question_en, "Glass"),)
    assert engine.decide(bottle, bottle_answer).item_id == "glass_beverage_bottle"
    assert engine.decide(cup, ((cup_question.question_en, "Paper"),)).outcome == "out_of_scope"
    assert engine.decide(bottle, bottle_answer).item_id == "glass_beverage_bottle"
    assert engine.decide(bottle).outcome == "clarify"


def test_second_answer_can_resolve_and_manual_correction_can_replace_it():
    engine = decision_engine()
    record = ambiguous("plastic_beverage_bottle", "glass_beverage_bottle")
    first = engine.decide(record)
    history = ((first.question_en, "Not sure"),)
    second = engine.decide(record, history)
    assert second.outcome == "clarify"
    result = engine.decide(record, history + ((second.question_en, "Plastic"),))
    assert result.item_id == "plastic_beverage_bottle"
    assert result.confirmed_by == "user_answer"
    corrected = engine.decide(record, history, corrected_item_id="glass_food_jar")
    assert corrected.item_id == "glass_food_jar"
    assert corrected.confirmed_by == "correction"
