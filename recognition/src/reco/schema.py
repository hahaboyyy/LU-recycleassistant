"""Output contract for module B: *what is in the photo*.

Deliberately narrow. B does not decide what should be done with an item
(module C owns that), so this schema has no advice field. It also has no
numeric confidence: the model is asked for observable evidence and an
explicit state of "unknown" instead. Any ``confidence``/``score`` style key
the model invents is stripped before validation (see ``parsing.py``), so
downstream code cannot accidentally depend on self-reported certainty.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, computed_field

SCHEMA_VERSION = "b-0.2"

_TRUE = {"yes", "y", "true", "1", "yes ", "是", "有", "present", "visible"}
_FALSE = {"no", "n", "false", "0", "否", "没有", "absent", "not visible"}
_UNKNOWN = {
    "",
    "unknown",
    "unk",
    "n/a",
    "na",
    "none",
    "null",
    "unsure",
    "not sure",
    "uncertain",
    "cannot tell",
    "can't tell",
    "unclear",
    "不确定",
    "未知",
    "看不清",
}


def _coerce_tri(value: Any) -> str:
    """Accept booleans, nulls and near-miss strings, collapse to tri-state."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).strip().lower()
    if text in _TRUE:
        return "yes"
    if text in _FALSE:
        return "no"
    return "unknown"


TriState = Annotated[Literal["yes", "no", "unknown"], BeforeValidator(_coerce_tri)]

#: Conditions module C may need before it can pick a rule.
#: Keys are stable; the English wording is what a follow-up question would say.
CONDITION_QUESTION: dict[str, str] = {
    "item": "What item is this?",
    "material": "What material is the item made of?",
    "is_empty": "Is the container empty?",
    "has_liquid": "Is there still liquid inside?",
    "has_residue": "Is there food or liquid residue on the item?",
    "is_clean": "Has the item been rinsed or wiped?",
    "is_damaged": "Is the item broken or damaged?",
    "has_multiple_components": "Does the item have parts that must be separated?",
}

TRIFIELDS: tuple[str, ...] = (
    "is_empty",
    "has_liquid",
    "has_residue",
    "is_clean",
    "is_damaged",
    "has_multiple_components",
)

#: Spoken hints for the "retake the photo" path (module D shows these).
ISSUE_HINT: dict[str, str] = {
    "blurry": "hold the phone steady or use better light",
    "too_dark": "shoot in brighter light",
    "too_far": "move closer so the item fills the frame",
    "cropped": "keep the whole item inside the frame",
    "multiple_objects": "show one main item at a time",
    "glare": "avoid direct glare or reflection",
    "occluded": "make sure nothing covers the item",
}


class Identification(BaseModel):
    """Card field 1 (shown to the user, in English)."""

    model_config = ConfigDict(extra="ignore")

    name_en: str = Field(description="Short English item name, e.g. 'plastic bottle'.")
    category_en: str = Field(default="", description="Coarse class, e.g. 'beverage container'.")
    alternatives_en: list[str] = Field(
        default_factory=list,
        description="Other plausible names when the photo is ambiguous.",
    )


class Material(BaseModel):
    """One candidate material. ``basis`` replaces a confidence number."""

    model_config = ConfigDict(extra="ignore")

    name_en: str = Field(description="e.g. 'PET plastic', 'aluminium', 'glass'.")
    role: Literal["primary", "component", "contaminant"] = "primary"
    basis: Literal["observed", "suspected"] = "suspected"
    evidence: str = Field(default="", description="Visible cue, e.g. 'transparent, embossed PET mark'.")


class VisibleState(BaseModel):
    """Observable conditions that change the disposal route. Unknown is fine."""

    model_config = ConfigDict(extra="ignore")

    is_empty: TriState = Field(default="unknown", description="Container has nothing inside.")
    has_liquid: TriState = Field(default="unknown", description="Liquid still inside.")
    has_residue: TriState = Field(default="unknown", description="Food/oil/liquid residue visible.")
    is_clean: TriState = Field(default="unknown", description="Rinsed or wiped.")
    is_damaged: TriState = Field(default="unknown", description="Broken, cracked or deformed.")
    has_multiple_components: TriState = Field(
        default="unknown",
        description="Mixed parts (e.g. cup + lid + straw) that may need separating.",
    )


class ImageQuality(BaseModel):
    model_config = ConfigDict(extra="ignore")

    usable: bool = True
    main_object_visible: TriState = "yes"
    issues: list[str] = Field(default_factory=list, description="blurry, too_dark, cropped, ...")


class Trace(BaseModel):
    """Per-call provenance. Written to the JSONL run log as well."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    created_at: str
    provider: str
    model: str
    latency_ms: int = 0
    attempts: int = 1
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    image_sha256: str = ""
    image_bytes: int = 0
    #: Which Role A rule catalogue this output was resolved against.
    catalogue_version: str = ""
    catalogue_sha256: str = ""


class RecognitionResult(BaseModel):
    """Module B's full output. ``unknown_conditions`` etc. are computed, not trusted."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = SCHEMA_VERSION
    identification: Identification
    #: Role A's catalogue is the only match key C uses (rules_v1.json: match_key=item_id).
    item_id: str = Field(
        default="unknown",
        description="One catalogue item_id, or 'unknown' / 'out_of_scope'.",
    )
    item_id_candidates: list[str] = Field(
        default_factory=list,
        description="Catalogue ids when more than one is plausible (drives the clarify path).",
    )
    catalogue_status: Literal["matched", "ambiguous", "out_of_scope", "unresolved"] = Field(
        default="unresolved",
        description="Set by our resolver in pipeline.py, mirroring C's outcome branches.",
    )
    catalogue_item_name_en: str = Field(
        default="", description="Canonical catalogue name once matched (what the card shows)."
    )
    materials: list[Material] = Field(default_factory=list)
    visible_state: VisibleState = Field(default_factory=VisibleState)
    other_unknowns: list[str] = Field(
        default_factory=list,
        description="Unknowns the model noticed outside the fixed condition list.",
    )
    image_quality: ImageQuality = Field(default_factory=ImageQuality)
    notes_en: str = Field(default="", description="One short sentence of extra observation.")
    trace: Trace | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unknown_conditions(self) -> list[str]:
        """Derived from the structured fields by *our* code, not self-reported."""
        keys: list[str] = []
        if self.catalogue_status != "matched":
            keys.append("item")
        if not self.materials:
            keys.append("material")
        for name in TRIFIELDS:
            if getattr(self.visible_state, name) == "unknown":
                keys.append(name)
        return keys

    @computed_field  # type: ignore[prop-decorator]
    @property
    def follow_up_questions_en(self) -> list[str]:
        """Raw material for module C's follow-up flow; C decides what to ask and caps it."""
        return [CONDITION_QUESTION[k] for k in self.unknown_conditions if k in CONDITION_QUESTION]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_new_photo(self) -> bool:
        """Retake only when the photo itself is unusable, not when the item is uncertain.

        Ambiguous wins: if we could list candidate items, the photo carries enough
        information to ask a clarifying question. Module C checks this flag first,
        so returning True here would turn a clarify case into a retake.
        """
        if self.catalogue_status == "ambiguous":
            return False
        return not self.image_quality.usable or self.image_quality.main_object_visible == "no"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_clarification(self) -> bool:
        """Ambiguous between catalogue ids -> C asks at most two questions."""
        return self.catalogue_status == "ambiguous"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name_en(self) -> str:
        """Card label: canonical catalogue name when matched, else the model's wording."""
        return self.catalogue_item_name_en or self.identification.name_en

    @computed_field  # type: ignore[prop-decorator]
    @property
    def retake_hint_en(self) -> str:
        if not self.needs_new_photo:
            return ""
        hints = [ISSUE_HINT.get(i, i.replace("_", " ")) for i in self.image_quality.issues]
        if not self.image_quality.usable and not hints:
            hints = ["use better light and keep the item in focus"]
        if not hints:
            hints = ["keep the whole item clearly in frame"]
        return "Please retake the photo: " + "; ".join(dict.fromkeys(hints)) + "."


class BaselineResult(BaseModel):
    """The 'just ask the model directly' baseline used for comparison by E."""

    model_config = ConfigDict(extra="ignore")

    identification: str
    disposal_advice: str
    notes_en: str = ""
    raw_text: str = ""
    trace: Trace | None = None
