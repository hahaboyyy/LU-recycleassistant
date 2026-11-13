"""Role C's session-based decision engine, with F's integration corrections."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


RULES_PATH = Path(__file__).resolve().parent / "data" / "rules_v1.json"
RULES_SHA256 = "0481fe079e6a7b093ebc62f8e5bed68108ba3aa3f70ec8b7e70ec4db7e96dc75"
BOTTLES = {"plastic_beverage_bottle", "glass_beverage_bottle"}
CANS = {"metal_food_can", "aluminium_beverage_can"}
OUTSIDE = "out_of_scope"
FALLBACKS = {
    "retake": "no_clear_object",
    "out_of_scope": "unsupported_item",
    "unresolved": "unresolved_item",
}


@dataclass
class Result:
    outcome: str
    item_id: str | None = None
    identification_name: str = ""
    disposal_advice: str = ""
    question_en: str = ""
    round_no: int = 1
    can_ask_again: bool = False
    trace: dict = field(default_factory=dict)
    question_key: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    choices: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _includes(text: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


class DecisionEngine:
    def __init__(self, rules_path: Path = RULES_PATH):
        raw = Path(rules_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != RULES_SHA256:
            raise ValueError("Role A's Rules v1.0.0 checksum does not match")
        self.rules = json.loads(raw)
        self.by_id = {rule["item_id"]: rule for rule in self.rules["rules"]}
        self.max_rounds = self.rules["max_clarification_rounds"]
        self._sessions: dict[str, tuple[dict, int]] = {}

    def decide(self, record: dict, user_reply: str | None = None, session_id: str = "default") -> Result:
        if user_reply is None:
            state = dict(record)
            state["_candidates"] = tuple(dict.fromkeys(
                item_id for item_id in record.get("item_id_candidates", []) if item_id in self.by_id
            ))
            round_no = 1
        else:
            previous = self._sessions.get(session_id)
            if previous is None:
                return self._fallback(record, "unresolved", 1)
            previous_record, previous_round = previous
            state = self._apply_reply(previous_record, user_reply)
            round_no = previous_round + 1
        result = self._decide_inner(state, round_no)
        self._sessions[session_id] = (state, round_no)
        return result

    def reset(self, session_id: str = "default") -> None:
        self._sessions.pop(session_id, None)

    def _decide_inner(self, record: dict, round_no: int) -> Result:
        if record.get("needs_new_photo"):
            return self._fallback(record, "retake", round_no)
        status = record.get("catalogue_status")
        if status in {"out_of_scope", "unresolved"}:
            return self._fallback(record, status, round_no)
        if status == "matched":
            rule = self.by_id.get(record.get("item_id"))
            if rule is None:
                return self._fallback(record, "unresolved", round_no)
            return Result(
                outcome="advice", item_id=rule["item_id"], identification_name=rule["item_name"],
                disposal_advice=rule["disposal_advice"], round_no=round_no,
                trace={
                    "rules_version": self.rules["rules_version"], "round_no": round_no,
                    "rule_id": rule["item_id"], "route_id": rule["route_id"],
                    "destination_scope": rule["destination_scope"], "destination": rule["destination"],
                    "source_ids": rule["source_ids"],
                    "confirmed_by": record.get("_confirmed_by", "model"),
                },
            )
        if status != "ambiguous" or not record["_candidates"] or round_no > self.max_rounds:
            return self._fallback(record, "unresolved", round_no)
        question = self._pick_question(record, round_no)
        if question.text in record.get("_asked_questions", ()):
            return self._fallback(record, "unresolved", round_no)
        record["_current_question"] = question
        options = tuple(label for label, _ in question.choices)
        return Result(
            outcome="clarify", question_en=question.text, round_no=round_no,
            can_ask_again=round_no < self.max_rounds, question_key=question.key,
            options=(*options, "Not sure") if len(options) < 8 else (),
            trace={"rules_version": self.rules["rules_version"], "round_no": round_no,
                   "question_key": question.key},
        )

    def _fallback(self, record: dict, outcome: str, round_no: int) -> Result:
        key = FALLBACKS[outcome]
        name = record.get("catalogue_item_name_en") or record.get("identification", {}).get("name_en", "")
        return Result(
            outcome=outcome, identification_name=name, disposal_advice=self.rules[key], round_no=round_no,
            trace={"rules_version": self.rules["rules_version"], "round_no": round_no, "fallback_key": key},
        )

    def _pick_question(self, record: dict, round_no: int) -> Question:
        ids = record["_candidates"]
        candidates = set(ids)
        if round_no == 1 and candidates == {"disposable_plastic_cup"}:
            return Question("material", "Is the cup made of rigid plastic or paper?", (
                ("Plastic", ("disposable_plastic_cup",)), ("Paper", (OUTSIDE,)),
            ))
        if round_no == 1 and candidates == {"foil_lined_snack_packet"}:
            return Question("lining", "Does the snack packet have a metallic inner lining?", (
                ("Yes", ("foil_lined_snack_packet",)), ("No", (OUTSIDE,)),
            ))
        if candidates <= CANS:
            return Question("package_type", "Was the can used for food or for a beverage?", (
                ("Food", ("metal_food_can",)), ("Beverage", ("aluminium_beverage_can",)),
            ))
        if candidates == {"glass_food_jar", "glass_beverage_bottle"}:
            return Question("package_type", "Was this a food jar or a beverage bottle?", (
                ("Jar", ("glass_food_jar",)), ("Bottle", ("glass_beverage_bottle",)),
            ))
        if candidates == BOTTLES and round_no > 1:
            return Question("item_label", "Does the label say the bottle is plastic or glass?", (
                ("Plastic", ("plastic_beverage_bottle",)), ("Glass", ("glass_beverage_bottle",)),
            ))
        # Tissue and office paper need an item choice even though A lists different paper materials.
        all_paper = all("paper" in self.by_id[item_id]["material"].casefold() for item_id in ids)
        if round_no == 1 and not all_paper:
            by_material: dict[str, list[str]] = {}
            for item_id in ids:
                by_material.setdefault(self.by_id[item_id]["material"], []).append(item_id)
            if len(by_material) > 1:
                return Question("material", "What material is the main item made of?",
                                tuple((material, tuple(items)) for material, items in by_material.items()))
        choices = tuple((self.by_id[item_id]["item_name"], (item_id,)) for item_id in ids)
        return Question("package_type", "Which item is shown in the photo?", choices)

    def _apply_reply(self, record: dict, reply: str) -> dict:
        state = dict(record)
        question = state.get("_current_question")
        if question is None:
            return state
        state["_asked_questions"] = (*state.get("_asked_questions", ()), question.text)
        selected = self._resolve_reply(state["_candidates"], question, reply)
        if selected is None:
            return state
        state["_confirmed_by"] = "user_answer"
        if selected == (OUTSIDE,):
            state.update(item_id=OUTSIDE, catalogue_status="out_of_scope")
        elif len(selected) == 1:
            item_id = selected[0]
            state.update(item_id=item_id, catalogue_status="matched",
                         catalogue_item_name_en=self.by_id[item_id]["item_name"])
        else:
            state["_candidates"] = selected
        return state

    def _resolve_reply(self, ids: tuple[str, ...], question: Question, reply: str) -> tuple[str, ...] | None:
        label_unknown = {"i cannot see the label", "i can t see the label", "the label is unreadable"}
        clauses = [_normalized(clause) for clause in re.split(r"[.!?]", reply)]
        answer = " ".join(clause for clause in clauses if clause and clause not in label_unknown)
        uncertain = ("not", "cannot", "can t", "don t", "isn t", "aren t", "doesn t",
                     "unsure", "unknown", "maybe", "probably", "might", "or")
        if any(_includes(answer, word) for word in uncertain):
            return None
        matches = []
        for item_id in ids:
            rule = self.by_id[item_id]
            labels = (item_id, rule["item_name"], *rule["aliases"])
            if any(_includes(answer, _normalized(label)) for label in labels):
                matches.append(item_id)
        if len(matches) == 1:
            return (matches[0],)
        if len(matches) > 1:
            return None
        if question.key == "lining":
            if _includes(answer, "no") or _includes(answer, "non metallic"):
                return (OUTSIDE,)
            if _includes(answer, "yes") or _includes(answer, "metallic"):
                return ("foil_lined_snack_packet",)
        selected = [targets for label, targets in question.choices if _includes(answer, _normalized(label))]
        return selected[0] if len(selected) == 1 else None
