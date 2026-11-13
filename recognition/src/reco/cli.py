"""``python -m reco`` -- command line entry point.

Subcommands
    recognize IMG...   structured recognition (module B)
    baseline  IMG...   direct-answer baseline (for E's comparison)
    catalogue          show the shared item catalogue (Role A, Rules v1.0)
    usage              token / latency / cost summary from the run log
    doctor             one live call to prove the API accepts images
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

from .catalog import CatalogueError, load_catalogue
from .client import ChatClient, LLMError
from .config import PRESETS, Config, load_config
from .mock import BAD_REPLIES, SCENARIOS, MockClient
from .pipeline import Recognizer
from .runlog import RunLog, summarize

SCENARIO_NAMES = tuple(SCENARIOS)
BAD_REPLY_NAMES = tuple(BAD_REPLIES)


def _client_for(cfg: Config, mock_scenario: str | None, fail_first: int, fail_with: str) -> object:
    if mock_scenario:
        return MockClient(scenario=mock_scenario, fail_first=fail_first, fail_with=fail_with)
    return ChatClient(cfg)


def _build(args: argparse.Namespace) -> Recognizer:
    overrides: dict[str, object] = {}
    if args.model:
        overrides["model"] = args.model
    if args.log:
        overrides["log_path"] = args.log
    if args.max_edge:
        overrides["image_max_edge"] = args.max_edge
    provider = args.provider or ("mock" if args.mock_scenario else None)
    cfg = load_config(provider, **overrides)
    if args.mock_scenario and not args.log:
        # keep demo calls out of the measured run log
        cfg = load_config(provider, **{**overrides, "log_path": "runs/mock.jsonl"})
    client = _client_for(cfg, args.mock_scenario, args.fail_first, getattr(args, "mock_break", "prose"))
    catalogue = load_catalogue(getattr(args, "catalogue", None) or cfg.catalogue_path or None)
    return Recognizer(cfg=cfg, client=client, log=RunLog(cfg.log_path), catalogue=catalogue)


def cmd_recognize(args: argparse.Namespace) -> int:
    rec = _build(args)
    failures = 0
    for image in args.images:
        outcome = rec.safe_recognize(image, note=args.note)
        payload = outcome.as_dict()
        if args.compact:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(_banner(image))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not outcome.ok:
            failures += 1
    return 1 if failures else 0


def cmd_baseline(args: argparse.Namespace) -> int:
    rec = _build(args)
    failures = 0
    for image in args.images:
        try:
            result = rec.baseline(image, note=args.note)
            print(_banner(image))
            print(result.model_dump_json(indent=2))
        except (LLMError, OSError) as exc:
            code = getattr(exc, "code", "ERROR")
            print(json.dumps({"image": image, "ok": False, "error": {"code": code, "message": str(exc)}},
                             ensure_ascii=False))
            failures += 1
    return 1 if failures else 0


def cmd_usage(args: argparse.Namespace) -> int:
    cfg = load_config(args.provider)
    path = args.log or cfg.log_path
    records = RunLog(path).read()
    if args.provider:
        records = [r for r in records if str(r.get("provider", "")) == args.provider]
    if args.note_prefix:
        records = [r for r in records if str(r.get("note", "")).startswith(args.note_prefix)]
    summary = summarize(records, price_in=args.price_in, price_out=args.price_out)
    print(f"log: {path}  (records used: {len(records)})")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args.provider)
    if args.mock_scenario:
        print("provider : mock (offline check, no network)")
        print(f"scenario : {args.mock_scenario}")
        return 0
    print(f"provider : {cfg.provider}")
    print(f"base_url : {cfg.base_url or '(mock)'}")
    print(f"model    : {cfg.model}")
    print(f"api key  : {'set' if cfg.api_key else 'MISSING'}")
    if args.mock_scenario:
        print("mode     : mock (no network)")
        return 0
    if not cfg.api_key:
        print("\nFAIL: no API key. export DEEPSEEK_API_KEY=... first.")
        return 2

    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (245, 245, 245)).save(buf, format="PNG")
    probe = buf.getvalue()
    client = ChatClient(cfg)
    messages = [
        {"role": "system", "content": "You are a health check. Reply with JSON only."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": 'Reply with exactly {"ok": true} and nothing else.'},
                {"type": "image_url", "image_url": {"url": _png_data_url(probe)}},
            ],
        },
    ]
    try:
        resp = client.chat(messages, max_tokens=32)
    except LLMError as exc:
        print(f"\nFAIL [{exc.code}]: {exc.message}")
        return 2 if exc.code == "AUTH" else 1
    print(f"\nOK  model={resp.model}  latency={resp.latency_ms}ms  "
          f"tokens={resp.prompt_tokens}/{resp.completion_tokens}")
    print(f"reply: {resp.text.strip()[:200]}")
    return 0


def cmd_catalogue(args: argparse.Namespace) -> int:
    """Show the shared item catalogue so B/C/E can confirm they are on one version."""
    cat = load_catalogue(args.catalogue or None)
    print(f"source  : {cat.source}")
    print(f"version : {cat.version}   items: {len(cat)}")
    print(f"sha256  : {cat.sha256}")
    print()
    print(f"{'item_id':32} {'item_name':30} material")
    print("-" * 82)
    for item in cat.items.values():
        print(f"{item.item_id:32} {item.item_name:30} {item.material}")
    return 0


def _png_data_url(raw: bytes) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _banner(image: str) -> str:
    return f"\n=== {image} ==="


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reco", description="LU Recycle Assistant - module B (recognition)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--provider", choices=sorted(PRESETS), default=None)
        p.add_argument("--model", default=None, help="override model name")
        p.add_argument("--log", default=None, help="JSONL run log path")
        p.add_argument("--note", default="", help="free-text label stored with each call")
        p.add_argument("--mock-scenario", choices=sorted(SCENARIO_NAMES), default=None,
                       help="offline demo without a key")
        p.add_argument("--mock-break", choices=sorted(BAD_REPLY_NAMES), default="prose",
                       help="which broken reply the mock returns first")
        p.add_argument("--fail-first", type=int, default=0, help="mock: break the first N replies")
        p.add_argument("--catalogue", default=None,
                       help="path to Role A's supported_items.csv (default: data/supported_items.csv)")

    p_rec = sub.add_parser("recognize", help="structured recognition")
    p_rec.add_argument("images", nargs="+")
    p_rec.add_argument("--compact", action="store_true")
    p_rec.add_argument("--max-edge", type=int, default=None)
    common(p_rec)
    p_rec.set_defaults(func=cmd_recognize)

    p_base = sub.add_parser("baseline", help="direct-answer baseline")
    p_base.add_argument("images", nargs="+")
    p_base.add_argument("--max-edge", type=int, default=None)
    common(p_base)
    p_base.set_defaults(func=cmd_baseline)

    p_use = sub.add_parser("usage", help="summarise the run log")
    p_use.add_argument("--log", default=None)
    p_use.add_argument("--provider", choices=sorted(PRESETS), default=None)
    p_use.add_argument("--price-in", type=float, default=None,
                       help="recompute cost from tokens: USD per 1M input tokens")
    p_use.add_argument("--price-out", type=float, default=None,
                       help="recompute cost from tokens: USD per 1M output tokens")
    p_use.add_argument("--note-prefix", default=None,
                       help="only count records whose note starts with this (e.g. dev-set-v2)")
    p_use.set_defaults(func=cmd_usage)

    p_doc = sub.add_parser("doctor", help="one live call to verify API + image input")
    p_doc.add_argument("--provider", choices=sorted(PRESETS), default=None)
    p_doc.add_argument("--mock-scenario", default=None)
    p_doc.set_defaults(func=cmd_doctor)

    p_cat = sub.add_parser("catalogue", help="show the shared item catalogue")
    p_cat.add_argument("--catalogue", default=None)
    p_cat.set_defaults(func=cmd_catalogue)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CatalogueError as exc:
        print(f"catalogue error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
