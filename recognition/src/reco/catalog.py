"""Catalogue of supported items, mirrored from Role A's handoff (Rules v1.0).

A's rules are keyed by ``item_id`` (``rules_v1.json`` has ``"match_key": "item_id"``).
A free-text item name therefore cannot drive the rule lookup: "plastic bottle"
has to become ``plastic_beverage_bottle`` before module C can do anything.

This module loads ``data/supported_items.csv`` (copied from A, hash-checked by a
test) and provides:

* ``Catalogue.resolve`` -- deterministic id / name / alias lookup, used as a
  post-processing step on whatever the model returned;
* ``Catalogue.prompt_block`` -- the compact table injected into the prompt so the
  model can pick an id in the first place.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_COLUMNS = ("item_id", "item_name", "aliases", "material", "scope")


class CatalogueError(Exception):
    """Catalogue missing or malformed."""


def _norm(text: str) -> str:
    """Normalise ids, names and aliases for exact comparison."""
    cleaned = (text or "").strip().lower().replace("_", " ").replace("-", " ")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class CatalogueItem:
    item_id: str
    item_name: str
    aliases: tuple[str, ...]
    material: str
    scope: str
    route_id: str = ""


@dataclass
class Catalogue:
    items: dict[str, CatalogueItem]
    sha256: str = ""
    version: str = "1.0.0"
    source: str = ""
    _index: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        index: dict[str, str] = {}
        for item in self.items.values():
            for candidate in (item.item_id, item.item_name, *item.aliases):
                key = _norm(candidate)
                if key and key not in index:
                    index[key] = item.item_id
        self._index = index

    def __len__(self) -> int:
        return len(self.items)

    def ids(self) -> list[str]:
        return list(self.items)

    def name_of(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.item_name if item else ""

    def resolve(self, raw: str | None) -> str | None:
        """Exact (normalised) match on id, English name or alias. No fuzzy guessing."""
        key = _norm(raw or "")
        if not key:
            return None
        return self._index.get(key)

    def resolve_many(self, raws: list[str] | None) -> list[str]:
        found: list[str] = []
        for raw in raws or []:
            hit = self.resolve(raw)
            if hit and hit not in found:
                found.append(hit)
        return found

    def material_vocabulary(self) -> list[str]:
        seen: list[str] = []
        for item in self.items.values():
            if item.material and item.material not in seen:
                seen.append(item.material)
        return seen

    def prompt_block(self, max_scope: int = 110) -> str:
        """Compact table for the prompt; scopes truncated to keep tokens low."""
        lines = ["item_id | item_name | aliases | material | scope"]
        for item in self.items.values():
            scope = item.scope if len(item.scope) <= max_scope else item.scope[: max_scope - 1].rstrip() + "…"
            aliases = " / ".join(item.aliases)
            lines.append(f"{item.item_id} | {item.item_name} | {aliases} | {item.material} | {scope}")
        return "\n".join(lines)


def default_path() -> Path:
    """Use the nearest catalogue, including the shared data in the integrated app."""
    source = Path(__file__).resolve()
    for root in source.parents[2:4]:
        candidate = root / "data" / "supported_items.csv"
        if candidate.is_file():
            return candidate
    return source.parents[2] / "data" / "supported_items.csv"


def load_catalogue(path: str | Path | None = None, version: str = "1.0.0") -> Catalogue:
    target = Path(path) if path else default_path()
    if not target.is_file():
        raise CatalogueError(
            f"item catalogue not found: {target}\n"
            "Copy supported_items.csv from Role A's handoff into data/, "
            "or set RECO_CATALOGUE=/path/to/supported_items.csv"
        )
    raw = target.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogueError(f"catalogue is not UTF-8: {exc}") from exc

    reader = csv.DictReader(text.splitlines())
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise CatalogueError(f"catalogue missing columns {missing}: {target}")

    items: dict[str, CatalogueItem] = {}
    for row in reader:
        item_id = (row.get("item_id") or "").strip()
        name = (row.get("item_name") or "").strip()
        if not item_id or not name:
            continue
        if item_id in items:
            raise CatalogueError(f"duplicate item_id {item_id!r} in {target}")
        aliases = tuple(a.strip() for a in (row.get("aliases") or "").split("|") if a.strip())
        items[item_id] = CatalogueItem(
            item_id=item_id,
            item_name=name,
            aliases=aliases,
            material=(row.get("material") or "").strip(),
            scope=(row.get("scope") or "").strip(),
            route_id=(row.get("route_id") or "").strip(),
        )
    if not items:
        raise CatalogueError(f"catalogue has no rows: {target}")
    return Catalogue(items=items, sha256=digest, version=version, source=str(target))
