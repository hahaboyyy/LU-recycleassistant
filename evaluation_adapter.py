"""Run E's visual protocol with B's baseline and the integrated decision service."""

from functools import cache
from pathlib import Path

from integration import decision_engine, live_recognizer
from photo import sanitize_photo


ACTIONS = {
    "advice": "give_advice",
    "clarify": "clarify_item",
    "out_of_scope": "out_of_scope",
    "retake": "no_clear_object",
    "unresolved": "unresolved_item",
}


@cache
def _recognizer():
    return live_recognizer()


# E's harness runs cases sequentially and immediately follows an initial answer.
_previous = None


def predict(*, mode, image_path, history):
    global _previous
    path = Path(image_path).resolve()
    if mode == "baseline":
        baseline = _recognizer().baseline(sanitize_photo(path.read_bytes()))
        return {
            "action": "give_advice", "identification": baseline.identification,
            "advice": baseline.disposal_advice,
            "input_tokens": baseline.trace.prompt_tokens,
            "output_tokens": baseline.trace.completion_tokens,
        }
    if mode != "improved":
        raise ValueError(f"Unknown evaluation arm: {mode}")
    if history:
        if _previous is None or _previous[0] != path:
            raise ValueError("An initial observation must precede clarification")
        record = _previous[1]
        input_tokens = output_tokens = 0
    else:
        _previous = None
        record = _recognizer().recognize(sanitize_photo(path.read_bytes()))
        _previous = (path, record)
        input_tokens = record.trace.prompt_tokens
        output_tokens = record.trace.completion_tokens
    answers = tuple((turn["question"], turn["answer"]) for turn in history)
    decision = decision_engine().decide(record, answers)
    return {
        "action": ACTIONS[decision.outcome], "identification": decision.identification or record.display_name_en,
        "item_id": decision.item_id, "advice": decision.disposal_advice,
        "question": decision.question_en, "question_key": decision.question_key,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
    }
