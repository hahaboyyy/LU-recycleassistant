"""Adapt B's record and D's full interaction history to Role C's decision engine."""

from dataclasses import dataclass

from backend import DATA_DIR
from module_c import DecisionEngine as ModuleC
from reco.catalog import Catalogue
from reco.schema import RecognitionResult


@dataclass(frozen=True)
class Decision:
    outcome: str
    identification: str = ""
    disposal_advice: str = ""
    item_id: str = ""
    question_en: str = ""
    question_key: str = ""
    options: tuple[str, ...] = ()
    round_no: int = 0
    route_id: str = ""
    destination: str = ""
    source_ids: tuple[str, ...] = ()
    fallback_key: str = ""
    confirmed_by: str = ""


class DecisionEngine:
    def __init__(self, catalogue: Catalogue) -> None:
        engine = ModuleC(DATA_DIR / "rules_v1.json")
        self.rules = engine.rules
        self.items = engine.by_id
        if self.items.keys() != catalogue.items.keys():
            raise ValueError("The catalogue IDs and rule IDs do not match")
        self.catalogue = catalogue
        self.max_rounds = self.rules["max_clarification_rounds"]

    def decide(self, record: RecognitionResult | None, answers=(), corrected_item_id=None) -> Decision:
        # A fresh C instance replays this photo's history, isolating users and retries.
        engine = ModuleC(DATA_DIR / "rules_v1.json")
        if corrected_item_id is not None:
            data = {"item_id": corrected_item_id, "catalogue_status": "matched", "_confirmed_by": "correction"}
        elif record is not None:
            data = record.model_dump()
        else:
            raise ValueError("Recognition is required before deciding")
        result = engine.decide(data)
        if corrected_item_id is None:
            for question, answer in answers[:self.max_rounds]:
                if result.outcome != "clarify" or question != result.question_en:
                    result = engine.decide({"catalogue_status": "unresolved"})
                    break
                result = engine.decide(data, user_reply=answer)
        trace = result.trace
        return Decision(
            outcome=result.outcome, identification=result.identification_name,
            disposal_advice=result.disposal_advice, item_id=result.item_id or "",
            question_en=result.question_en, question_key=result.question_key, options=result.options,
            round_no=min(len(answers), self.max_rounds), route_id=trace.get("route_id", ""),
            destination=trace.get("destination", ""), source_ids=tuple(trace.get("source_ids", ())),
            fallback_key=trace.get("fallback_key", ""), confirmed_by=trace.get("confirmed_by", ""),
        )
