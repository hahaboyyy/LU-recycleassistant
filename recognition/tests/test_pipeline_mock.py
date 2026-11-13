import json

from reco.client import ChatClient
from reco.config import load_config
from reco.mock import MockClient
from reco.pipeline import RecognitionFailure, Recognizer
from reco.runlog import RunLog, summarize
from reco.schema import Identification, RecognitionResult


def _recognizer(tmp_path, **mock_kw):
    cfg = load_config("mock", log_path=str(tmp_path / "runs.jsonl"))
    client = MockClient(**mock_kw)
    return Recognizer(cfg=cfg, client=client), tmp_path / "runs.jsonl"


def test_recognize_matches_catalogue_id(tmp_path, photo):
    rec, log_path = _recognizer(tmp_path, scenario="bottle")
    result = rec.recognize(photo, note="unit")

    assert result.item_id == "plastic_beverage_bottle"
    assert result.catalogue_status == "matched"
    assert result.catalogue_item_name_en == "Plastic beverage bottle"
    assert result.display_name_en == "Plastic beverage bottle"
    assert result.trace is not None and result.trace.attempts == 1
    assert result.trace.catalogue_version == "1.0.0"
    assert result.trace.catalogue_sha256

    rows = RunLog(log_path).read()
    assert len(rows) == 1
    assert rows[0]["mode"] == "pipeline" and rows[0]["ok"] is True
    assert rows[0]["note"] == "unit"
    assert rows[0]["item_id"] == "plastic_beverage_bottle"
    assert rows[0]["catalogue_status"] == "matched"
    assert rows[0]["image_sha256"] == result.trace.image_sha256


def test_ambiguous_item_drives_clarification(tmp_path, photo):
    rec, _ = _recognizer(tmp_path, scenario="ambiguous")
    result = rec.recognize(photo)
    assert result.item_id == "unknown"
    assert result.catalogue_status == "ambiguous"
    assert result.item_id_candidates == ["plastic_beverage_bottle", "glass_beverage_bottle"]
    assert result.needs_clarification is True
    assert result.needs_new_photo is False
    assert "item" in result.unknown_conditions


def test_out_of_scope_item(tmp_path, photo):
    rec, _ = _recognizer(tmp_path, scenario="out_of_scope")
    result = rec.recognize(photo)
    assert result.item_id == "out_of_scope"
    assert result.catalogue_status == "out_of_scope"
    assert result.needs_clarification is False


def test_bad_photo_is_unresolved_and_needs_retake(tmp_path, photo):
    rec, _ = _recognizer(tmp_path, scenario="bad_photo")
    result = rec.recognize(photo)
    assert result.catalogue_status == "unresolved"
    assert result.needs_new_photo is True
    assert "Please retake" in result.retake_hint_en
    assert result.image_quality.issues == ["blurry", "too_dark"]


def test_repair_path_retries_once_then_succeeds(tmp_path, photo):
    rec, log_path = _recognizer(tmp_path, scenario="bottle", fail_first=1, fail_with="prose")
    result = rec.recognize(photo)
    assert result.trace.attempts == 2

    rows = RunLog(log_path).read()
    assert len(rows) == 2
    assert rows[0]["parse_ok"] is False and rows[0]["error_code"] == "PARSE"
    assert rows[1]["parse_ok"] is True


def test_fenced_reply_is_accepted_without_repair(tmp_path, photo):
    rec, _ = _recognizer(tmp_path, scenario="bottle", fail_first=1, fail_with="fenced")
    result = rec.recognize(photo)
    assert result.trace.attempts == 1
    assert result.item_id == "plastic_beverage_bottle"


def test_gives_up_after_two_bad_replies(tmp_path, photo):
    rec, _ = _recognizer(tmp_path / "raise", scenario="bottle", fail_first=2, fail_with="prose")
    try:
        rec.recognize(photo)
    except RecognitionFailure as exc:
        assert exc.code == "PARSE"
    else:  # pragma: no cover
        raise AssertionError("expected RecognitionFailure")

    # a fresh mock, because the first one has already used up its bad replies
    rec2, _ = _recognizer(tmp_path / "safe", scenario="bottle", fail_first=2, fail_with="prose")
    outcome = rec2.safe_recognize(photo)
    assert outcome.ok is False and outcome.error_code == "PARSE"
    assert "error" in outcome.as_dict()


def test_baseline_answers_directly(tmp_path, photo):
    rec, log_path = _recognizer(tmp_path, scenario="bottle")
    base = rec.baseline(photo)
    assert "bottle" in base.identification.lower()
    assert base.disposal_advice
    rows = RunLog(log_path).read()
    assert rows[0]["mode"] == "baseline"
    assert json.loads(base.model_dump_json())["identification"]


def test_missing_api_key_is_reported_not_raised(tmp_path, photo):
    cfg = load_config("deepseek", api_key="", log_path=str(tmp_path / "runs.jsonl"))
    rec = Recognizer(cfg=cfg, client=ChatClient(cfg), log=RunLog(cfg.log_path))
    outcome = rec.safe_recognize(photo)
    assert outcome.ok is False
    assert outcome.error_code == "AUTH"


def test_usage_summary(tmp_path, photo):
    rec, log_path = _recognizer(tmp_path, scenario="bottle")
    rec.recognize(photo)
    rec.baseline(photo)
    summary = summarize(RunLog(log_path).read())
    assert summary["calls"] == 2
    assert summary["by_mode"] == {"pipeline": 1, "baseline": 1}
    assert summary["total_tokens"] > 0
    assert summary["latency_ms_p95"] is not None


# -- catalogue resolver (no model involved) --------------------------------
def _bare_result(**kw):
    base = {"identification": {"name_en": "Plastic beverage bottle"}}
    base.update(kw)
    return RecognitionResult.model_validate(base)


def test_resolver_falls_back_to_name_when_id_is_wrong(tmp_path):
    rec, _ = _recognizer(tmp_path)
    result = _bare_result(item_id="bottle_type_1", identification={"name_en": "glass soda bottle"})
    rec._apply_catalogue(result)
    assert result.item_id == "glass_beverage_bottle"
    assert result.catalogue_status == "matched"


def test_resolver_turns_unknown_id_into_ambiguous_or_unresolved(tmp_path):
    rec, _ = _recognizer(tmp_path)
    unresolved = _bare_result(item_id="mystery_thing", identification={"name_en": "something"})
    rec._apply_catalogue(unresolved)
    assert unresolved.catalogue_status == "unresolved"
    assert unresolved.item_id == "unknown"

    ambiguous = _bare_result(
        item_id="bottle",
        item_id_candidates=["plastic_beverage_bottle", "glass_beverage_bottle"],
        identification={"name_en": "bottle"},
    )
    rec._apply_catalogue(ambiguous)
    assert ambiguous.catalogue_status == "ambiguous"
    assert ambiguous.needs_clarification is True


def test_resolver_accepts_out_of_scope_marker(tmp_path):
    rec, _ = _recognizer(tmp_path)
    result = _bare_result(item_id="out-of-scope", identification={"name_en": "battery"})
    rec._apply_catalogue(result)
    assert result.catalogue_status == "out_of_scope"
    assert result.item_id == "out_of_scope"
