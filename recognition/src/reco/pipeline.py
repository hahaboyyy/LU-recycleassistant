"""The orchestration layer: one image in, one validated object out.

Two entry points on purpose:

* ``Recognizer.recognize`` -- structured, contract-bound output (module B).
* ``Recognizer.baseline``  -- "just ask the model" answer (comparison baseline).

Both share image preparation, provider config and logging, so module E can
compare them without hidden differences in how the image was sent.
"""

from __future__ import annotations

import uuid
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .catalog import Catalogue, load_catalogue
from .client import ChatClient, LLMError
from .config import Config, load_config
from .imageprep import ImageError, PreparedImage, prepare_image
from .parsing import JSONExtractError, SchemaError, parse_baseline, parse_result
from .prompts import (
    REPAIR_INSTRUCTION,
    build_baseline_messages,
    build_messages,
)
from .runlog import RunLog
from .schema import BaselineResult, RecognitionResult, Trace

#: One repair retry. Two model calls worst case per image, which keeps cost bounded.
MAX_PARSE_ATTEMPTS = 2


class RecognitionFailure(Exception):
    """Pipeline gave up. ``code`` is stable for UI and analysis."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Outcome:
    ok: bool
    result: RecognitionResult | None = None
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.ok and self.result is not None:
            data = self.result.model_dump()
            data["ok"] = True
            return data
        return {"ok": False, "error": {"code": self.error_code, "message": self.error_message}}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_run_id() -> str:
    return f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


class Recognizer:
    def __init__(
        self,
        cfg: Config | None = None,
        client: Any | None = None,
        log: RunLog | None = None,
        catalogue: Catalogue | None = None,
    ) -> None:
        self.cfg = cfg or load_config()
        self.client = client or ChatClient(self.cfg)
        self.log = log or RunLog(self.cfg.log_path)
        self.catalogue = catalogue or load_catalogue(self.cfg.catalogue_path or None)
        self._catalogue_block = self.catalogue.prompt_block()
        self.run_id = _new_run_id()

    # -- structured recognition -----------------------------------------
    def recognize(self, image: str | bytes, *, note: str = "", clarification: str = "") -> RecognitionResult:
        prep = prepare_image(image, self.cfg.image_max_edge, self.cfg.jpeg_quality)
        messages = build_messages(prep, self._catalogue_block, clarification, self.cfg.strict_scope)

        latency_total = 0
        prompt_tokens = 0
        completion_tokens = 0
        calls = 0
        result: RecognitionResult | None = None
        last_reason = ""

        for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
            try:
                resp = self.client.chat(messages)
            except LLMError as exc:
                self._log("pipeline", prep, attempt, ok=False, error_code=exc.code, note=note)
                raise

            calls += 1
            latency_total += resp.latency_ms
            prompt_tokens += resp.prompt_tokens or 0
            completion_tokens += resp.completion_tokens or 0

            try:
                result, _dropped = parse_result(resp.text)
                self._apply_catalogue(result)
            except (JSONExtractError, SchemaError) as exc:
                last_reason = str(exc)
                self._log(
                    "pipeline",
                    prep,
                    attempt,
                    ok=True,
                    parse_ok=False,
                    error_code="PARSE",
                    note=note,
                    resp=resp,
                )
                if attempt >= MAX_PARSE_ATTEMPTS:
                    raise RecognitionFailure(
                        "PARSE", f"model reply did not match the contract after {attempt} attempts: {last_reason}"
                    ) from exc
                # Show the model its own bad reply plus the reason, then ask again.
                messages = [
                    *messages,
                    {"role": "assistant", "content": resp.text[:4000]},
                    {"role": "user", "content": REPAIR_INSTRUCTION.format(reason=last_reason[:220])},
                ]
                continue

            self._log(
                "pipeline",
                prep,
                attempt,
                ok=True,
                parse_ok=True,
                note=note,
                resp=resp,
                item_id=result.item_id,
                catalogue_status=result.catalogue_status,
            )
            break

        if result is None:  # pragma: no cover - loop always breaks or raises
            raise RecognitionFailure("PARSE", last_reason or "no result")

        if (not clarification.strip() and self.cfg.provider not in {"mock", "fixture"}
                and self._needs_identity_review(result)):
            # One extra visual check, without reference labels or user answers.
            # Missing materials/linings still belong to clarification, not guessing.
            review_messages = build_messages(prep, self._catalogue_block, "", self.cfg.strict_scope)
            review_messages[0]["content"] += (
                "\n\nThis is one visual identity review. Re-examine the original image, "
                "especially object construction and visible edges. The following IDs "
                "are hypotheses, not correct labels: " + ", ".join(self._review_candidates(result)) + ". "
                "Use visible evidence to select the most appropriate catalogue item. "
                "A printed or crumpled sheet can still be office paper. Check whether "
                "a soft paper item is a facial tissue rather than a carrier bag. "
                "Do not assume toy use from bright colour alone. You may keep unknown "
                "when evidence is insufficient. Do not guess hidden material or lining."
            )
            try:
                review = self.client.chat(review_messages)
                calls += 1
                latency_total += review.latency_ms
                prompt_tokens += review.prompt_tokens or 0
                completion_tokens += review.completion_tokens or 0
                checked, _ = parse_result(review.text)
                self._apply_catalogue(checked)
                self._log("identity_review", prep, calls, ok=True, parse_ok=True,
                          note=note, resp=review, item_id=checked.item_id,
                          catalogue_status=checked.catalogue_status)
                result = checked
            except (LLMError, JSONExtractError, SchemaError) as exc:
                self._log("identity_review", prep, calls + 1, ok=False,
                          error_code=getattr(exc, "code", "PARSE"), note=note)
                # The original valid uncertain result remains useful for a question.

        result.trace = Trace(
            run_id=self.run_id,
            created_at=_now(),
            provider=self.cfg.provider,
            model=self.cfg.model,
            latency_ms=latency_total,
            attempts=calls,
            prompt_tokens=prompt_tokens or None,
            completion_tokens=completion_tokens or None,
            cost_usd=self.cfg.cost_usd(prompt_tokens or None, completion_tokens or None),
            image_sha256=prep.sha256,
            image_bytes=prep.nbytes,
            catalogue_version=self.catalogue.version,
            catalogue_sha256=self.catalogue.sha256,
        )
        return result

    def _review_candidates(self, result: RecognitionResult) -> list[str]:
        candidates = list(result.item_id_candidates)
        if result.catalogue_status == "out_of_scope":
            alternatives = " ".join(result.identification.alternatives_en).casefold()
            for item_id, item in self.catalogue.items.items():
                labels = (item.item_name, *item.aliases)
                if any(re.search(r"\b" + re.escape(label.casefold()) + r"\b", alternatives)
                       for label in labels):
                    candidates.append(item_id)
        return list(dict.fromkeys(candidates))

    def _needs_identity_review(self, result: RecognitionResult) -> bool:
        if result.needs_new_photo:
            return False
        candidates = self._review_candidates(result)
        if not candidates or result.catalogue_status not in {"ambiguous", "out_of_scope"}:
            return False
        scope_critical = {"disposable_plastic_cup", "foil_lined_snack_packet", "beverage_carton"}
        if set(candidates) & scope_critical:
            return False
        materials = {self.catalogue.items[c].material.casefold() for c in candidates}
        # Different-material candidates require user evidence. Similar paper
        # categories or an explicit supported alternative can be checked visually.
        return len(materials) == 1 or all("paper" in m for m in materials)

    # -- direct-answer baseline -----------------------------------------
    def baseline(self, image: str | bytes, *, note: str = "") -> BaselineResult:
        prep = prepare_image(image, self.cfg.image_max_edge, self.cfg.jpeg_quality)
        messages = build_baseline_messages(prep)
        try:
            resp = self.client.chat(messages)
        except LLMError as exc:
            self._log("baseline", prep, 1, ok=False, error_code=exc.code, note=note)
            raise
        self._log("baseline", prep, 1, ok=True, parse_ok=True, note=note, resp=resp)
        result = parse_baseline(resp.text)
        result.trace = Trace(
            run_id=self.run_id,
            created_at=_now(),
            provider=self.cfg.provider,
            model=self.cfg.model,
            latency_ms=resp.latency_ms,
            attempts=resp.attempts,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            cost_usd=self.cfg.cost_usd(resp.prompt_tokens, resp.completion_tokens),
            image_sha256=prep.sha256,
            image_bytes=prep.nbytes,
        )
        return result

    # -- never-raises wrapper for UI / batch code ------------------------
    def safe_recognize(self, image: str | bytes, *, note: str = "", clarification: str = "") -> Outcome:
        try:
            return Outcome(ok=True, result=self.recognize(image, note=note, clarification=clarification))
        except RecognitionFailure as exc:
            return Outcome(ok=False, error_code=exc.code, error_message=exc.message)
        except ImageError as exc:
            return Outcome(ok=False, error_code="IMAGE", error_message=str(exc))
        except LLMError as exc:
            return Outcome(ok=False, error_code=exc.code, error_message=exc.message)
        except Exception as exc:  # noqa: BLE001 - last resort, keep the UI alive
            return Outcome(ok=False, error_code="INTERNAL", error_message=f"{type(exc).__name__}: {exc}")

    # -- catalogue resolution -------------------------------------------
    def _apply_catalogue(self, result: RecognitionResult) -> None:
        """Turn whatever the model said into Role A's match key, deterministically.

        Exact id / name / alias matching only -- no fuzzy scoring. For module C a
        wrong confident match is worse than an honest "ambiguous".
        """
        raw = (result.item_id or "").strip()
        if raw.lower().replace("-", "_") in {"out_of_scope", "outside", "unsupported"}:
            result.item_id = "out_of_scope"
            result.item_id_candidates = []
            result.catalogue_status = "out_of_scope"
            result.catalogue_item_name_en = ""
            return

        hit = self.catalogue.resolve(raw)
        candidates = self.catalogue.resolve_many(result.item_id_candidates)
        # Contradictory structured candidates are unresolved evidence, even when
        # the primary ID is valid. Do not silently discard the alternatives.
        if hit and any(candidate != hit for candidate in candidates):
            candidates = list(dict.fromkeys([hit, *candidates]))
            hit = None
        if not hit and not candidates:
            candidates = self.catalogue.resolve_many(result.identification.alternatives_en)

        # An unresolved ID with candidates needs confirmation. A matching display
        # name must not erase that uncertainty, even for one scope-limited item.
        if not hit and not candidates:
            hit = self.catalogue.resolve(result.identification.name_en)
        if hit:
            result.item_id = hit
            result.catalogue_item_name_en = self.catalogue.name_of(hit)
            result.catalogue_status = "matched"
            result.item_id_candidates = [
                c for c in self.catalogue.resolve_many(result.item_id_candidates) if c != hit
            ]
            return

        result.item_id = "unknown"
        result.item_id_candidates = candidates
        result.catalogue_status = "ambiguous" if candidates else "unresolved"
        result.catalogue_item_name_en = ""

    # -- logging ---------------------------------------------------------
    def _log(
        self,
        mode: str,
        prep: PreparedImage,
        call_index: int,
        *,
        ok: bool,
        parse_ok: bool | None = None,
        error_code: str | None = None,
        note: str = "",
        resp: Any | None = None,
        item_id: str | None = None,
        catalogue_status: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "ts": _now(),
            "run_id": self.run_id,
            "mode": mode,
            "call_index": call_index,
            "provider": self.cfg.provider,
            "model": self.cfg.model,
            "image_sha256": prep.sha256,
            "image_bytes": prep.nbytes,
            "latency_ms": getattr(resp, "latency_ms", 0) if resp else 0,
            "prompt_tokens": getattr(resp, "prompt_tokens", None) if resp else None,
            "completion_tokens": getattr(resp, "completion_tokens", None) if resp else None,
            "ok": ok,
            "parse_ok": parse_ok,
            "error_code": error_code,
            "note": note,
            "item_id": item_id,
            "catalogue_status": catalogue_status,
        }
        record["total_tokens"] = (record["prompt_tokens"] or 0) + (record["completion_tokens"] or 0) or None
        record["cost_usd"] = self.cfg.cost_usd(record["prompt_tokens"], record["completion_tokens"])
        try:
            self.log.write(record)
        except OSError:
            pass  # never let logging break recognition
