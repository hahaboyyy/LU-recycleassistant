import argparse
import csv
import hashlib
import importlib
import json
import math
import random
import statistics
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RULE_HASH = "0481fe079e6a7b093ebc62f8e5bed68108ba3aa3f70ec8b7e70ec4db7e96dc75"
ARMS = ("baseline_photo", "rules_photo", "rules_interactive")
ACTIONS = {"give_advice", "clarify_item", "out_of_scope", "no_clear_object", "unresolved_item"}
RESPONSE_FIELDS = ("action", "item_id", "identification", "advice", "question", "question_key")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_key(original_id):
    key = original_id.strip().casefold().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    parts = key.split("/")
    if len(parts) > 5 and parts[2].endswith("flickr.com") and parts[3] == "photos":
        return f"flickr:{parts[5]}"
    return key


def manifest():
    return read_csv(DATA / "formal_cases.csv")


def validate(cases):
    if sha(DATA / "rules_v1.json") != RULE_HASH:
        raise ValueError("rules_v1.json does not match Role A's release checksum")
    rules = json.loads((DATA / "rules_v1.json").read_bytes())
    catalog = {entry["item_id"]: entry for entry in rules["rules"]}
    if len(cases) != 60 or len({case["case_id"] for case in cases}) != 60:
        raise ValueError("Expected 60 unique formal case IDs")
    if Counter(case["case_type"] for case in cases) != {
        "clear_supported": 48, "ambiguous": 8, "clear_unsupported": 3, "no_clear_object": 1
    }:
        raise ValueError("Unexpected formal-case distribution")
    if Counter(c["expected_final_item_id"] for c in cases if c["case_type"] == "clear_supported") != {
        item_id: 3 for item_id in catalog
    }:
        raise ValueError("Expected three clear cases per supported item")
    for case in cases:
        cid = case["case_id"]
        final_action = case["expected_final_action"]
        first_action = case["expected_initial_action"]
        if case["rules_version"] != rules["rules_version"] or final_action not in ACTIONS - {"clarify_item"}:
            raise ValueError(f"{cid}: invalid rule version or final action")
        item_id = case["expected_final_item_id"]
        if final_action == "give_advice":
            expected = catalog.get(item_id)
            fields = {"route_id": "expected_route_id", "destination_scope": "expected_destination_scope",
                      "destination": "expected_destination", "disposal_advice": "expected_final_advice"}
            if not expected or any(expected[k] != case[v] for k, v in fields.items()):
                raise ValueError(f"{cid}: reference does not match Rules v1.0.0")
        else:
            fallback_key = "unsupported_item" if final_action == "out_of_scope" else final_action
            if item_id or case["expected_route_id"] or case["expected_final_advice"] != rules[fallback_key]:
                raise ValueError(f"{cid}: incorrect fallback reference")
        expected_first_action = {
            "clear_supported": "give_advice", "clear_unsupported": "out_of_scope",
            "no_clear_object": "no_clear_object", "ambiguous": "clarify_item"
        }[case["case_type"]]
        if first_action != expected_first_action or (first_action != "clarify_item" and final_action != first_action):
            raise ValueError(f"{cid}: inconsistent expected actions")
        has_fixture = first_action == "clarify_item"
        if bool(case["question_key_1"]) != has_fixture or bool(case["user_answer_1"]) != has_fixture:
            raise ValueError(f"{cid}: inconsistent first question fixture")
        if bool(case["question_key_2"]) != bool(case["user_answer_2"]) or (case["question_key_2"] and not has_fixture):
            raise ValueError(f"{cid}: inconsistent second question fixture")


def check_photos(cases):
    from PIL import Image

    exclusions = read_csv(DATA / "dev_exclusions.csv")
    originals = {source_key(row["original_id"]) for row in exclusions}
    digests = {row["sha256"] for row in exclusions}
    ready = {}
    problems = []
    for case in cases:
        cid = case["case_id"]
        image_path = (ROOT / case["image_path"]).resolve()
        original = source_key(case["original_id"])
        if not original or not case["photo_credit_license"].strip():
            problems.append(f"{cid}: needs original ID and photo credit")
        if case["a_review"].strip().lower() != "approved":
            problems.append(f"{cid}: needs A approval")
        if original and original in originals:
            problems.append(f"{cid}: original is already used")
        if original:
            originals.add(original)
        if not image_path.is_relative_to(ROOT / "photos") or not image_path.is_file():
            problems.append(f"{cid}: missing photo under photos/")
            continue
        try:
            with Image.open(image_path) as photo:
                photo.verify()
            digest = sha(image_path)
        except (OSError, ValueError, SyntaxError):
            problems.append(f"{cid}: unreadable photo")
            continue
        if digest in digests:
            problems.append(f"{cid}: exact photo duplicate")
        digests.add(digest)
        ready[cid] = {"path": image_path, "sha256": digest}
    return ready, problems


def invoke(predict, mode, image_path, history):
    start = time.perf_counter()
    try:
        response = predict(mode=mode, image_path=image_path, history=history)
        if not isinstance(response, dict):
            raise TypeError("The adapter must return a dictionary")
        if any(not isinstance(response.get(field, ""), str) for field in RESPONSE_FIELDS):
            raise TypeError("Response fields must be strings")
        output = {field: response.get(field, "").strip() for field in RESPONSE_FIELDS}
        if output["action"] not in ACTIONS:
            raise ValueError("Missing or invalid action")
        text_field = "question" if output["action"] == "clarify_item" else "advice"
        if not output[text_field]:
            raise ValueError("Missing user-facing text")
        for name in ("input_tokens", "output_tokens"):
            count = response.get(name)
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("Token counts must be nonnegative integers")
            output[name] = count
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2), **output}
    except Exception as error:
        return {"status": "error", "error_type": type(error).__name__,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2)}


def interactive(predict, first, image_path, case):
    calls = [first]
    history = []
    stop_reason = ""
    while calls[-1]["status"] == "ok" and calls[-1]["action"] == "clarify_item":
        next_turn = len(history) + 1
        if next_turn > 2:
            stop_reason = "turn_limit_exceeded"
            break
        key = case[f"question_key_{next_turn}"]
        output = calls[-1]
        if not key or output["question_key"] != key:
            stop_reason = "question_without_fixture"
            break
        history.append({"question": output["question"], "answer": case[f"user_answer_{next_turn}"]})
        calls.append(invoke(predict, "improved", image_path, [dict(turn) for turn in history]))
    return calls, history, stop_reason


def run(args, cases, photos):
    module_name, separator, function_name = args.adapter.partition(":")
    if not separator:
        raise ValueError("Pass an adapter as module:function")
    predict = getattr(importlib.import_module(module_name), function_name)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "run.jsonl").open("x", encoding="utf-8") as log:
        def append(record):
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()

        append({"kind": "metadata", "model": args.model, "baseline_revision": args.baseline_revision,
                "improved_revision": args.improved_revision, "seed": args.seed,
                "manifest_sha256": sha(DATA / "formal_cases.csv"), "rules_sha256": RULE_HASH})
        ordered = list(cases)
        rng = random.Random(args.seed)
        rng.shuffle(ordered)
        for case in ordered:
            cid = case["case_id"]
            photo = photos[cid]
            order = ["baseline", "improved"]
            rng.shuffle(order)

            def record(arm, calls, history=(), stop_reason=""):
                append({"kind": "result", "case_id": cid, "arm": arm, "image_sha256": photo["sha256"],
                        "calls": calls, "history": list(history), "stop_reason": stop_reason})

            for mode in order:
                first = invoke(predict, mode, photo["path"], [])
                if mode == "baseline":
                    record("baseline_photo", [first])
                else:
                    record("rules_photo", [first])
                    record("rules_interactive", *interactive(predict, first, photo["path"], case))
            print(f"Recorded {cid}", flush=True)


def grade_sheet(run_dir, cases):
    records = [json.loads(line) for line in (run_dir / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    if not records or records[0].get("manifest_sha256") != sha(DATA / "formal_cases.csv"):
        raise ValueError("Run and manifest do not match")
    cases_by_id = {case["case_id"]: case for case in cases}
    rows = []
    for record in records[1:]:
        case = cases_by_id[record["case_id"]]
        arm = record["arm"]
        calls = record["calls"]
        last = calls[-1]
        first = calls[0]
        is_interactive = arm == "rules_interactive"
        is_ambiguous = case["case_type"] == "ambiguous"
        expected_action = case["expected_final_action" if is_interactive else "expected_initial_action"]
        expected_id = case["expected_final_item_id"] if expected_action == "give_advice" else ""
        action_ok = last.get("action") == expected_action
        need_question_review = is_ambiguous and first.get("action") == "clarify_item"
        need_advice_review = expected_action != "clarify_item" and action_ok
        failure_code = record["stop_reason"] or last.get("error_type", "")
        if not failure_code and not action_ok:
            failure_code = "wrong_action"
        grade_id = bool(expected_id) and arm != "baseline_photo"
        if not failure_code and grade_id and last.get("item_id") != expected_id:
            failure_code = "wrong_item"
        rows.append({
            "case_id": case["case_id"], "case_type": case["case_type"], "arm": arm,
            "status": last["status"], "error_type": last.get("error_type", ""),
            "stop_reason": record["stop_reason"], "expected_action": expected_action,
            "observed_action": last.get("action", ""), "action_correct": int(action_ok),
            "expected_item_id": expected_id, "observed_item_id": last.get("item_id", ""),
            "observed_identification": last.get("identification", ""),
            "identification_correct": (
                int(last.get("item_id") == expected_id) if grade_id else "NA"
            ),
            "expected_route_id": case["expected_route_id"] if expected_id else "",
            "expected_destination": case["expected_destination"] if expected_id else "",
            "accepted_alternative": case["accepted_alternative_destination"] if expected_id else "",
            "required_preparation": case["required_preparation"] if expected_id else "",
            "expected_advice": case["expected_final_advice"] if expected_action != "clarify_item" else "",
            "observed_advice": last.get("advice", ""),
            "questions_asked": " | ".join(call["question"] for call in calls if call.get("question")),
            "fixture_answers": " | ".join(turn["answer"] for turn in record["history"]),
            "followup_count": sum(call.get("action") == "clarify_item" for call in calls),
            "answers_supplied": len(record["history"]),
            "latency_ms": round(sum(call["latency_ms"] for call in calls), 2),
            "advice_correct": "REVIEW" if need_advice_review else "NA" if expected_action == "clarify_item" else 0,
            "question_appropriate": "REVIEW" if need_question_review else 0 if is_ambiguous else "NA",
            "failure_code": failure_code,
            "review_notes": "",
        })
    keys = [(row["case_id"], row["arm"]) for row in rows]
    expected_keys = {(cid, arm) for cid in cases_by_id for arm in ARMS}
    if len(keys) != len(expected_keys) or set(keys) != expected_keys:
        raise ValueError("Run is incomplete or contains duplicate case-arm results; retain its raw log")
    path = run_dir / "per_case.csv"
    if path.exists():
        raise FileExistsError(path)
    write_csv(path, sorted(rows, key=lambda row: (row["case_id"], ARMS.index(row["arm"]))))


def summarize(run_dir, chart):
    rows = read_csv(run_dir / "per_case.csv")
    expected_keys = {(case["case_id"], arm) for case in manifest() for arm in ARMS}
    if len(rows) != len(expected_keys) or {(r["case_id"], r["arm"]) for r in rows} != expected_keys:
        raise ValueError("The grading sheet must contain each case and arm exactly once")
    metrics = ("identification_correct", "advice_correct", "question_appropriate")
    if any(row[metric] not in {"0", "1", "NA"} for row in rows for metric in metrics):
        raise ValueError("Finish all REVIEW cells before summarizing")
    summary = []

    def emit(group, arm, metric, denominator, numerator, value):
        summary.append({"case_type": group, "arm": arm, "metric": metric, "n": denominator,
                        "numerator": numerator, "value": value})

    for arm in ARMS:
        for group in ("all", "clear_supported", "ambiguous", "clear_unsupported", "no_clear_object"):
            subset = [r for r in rows if r["arm"] == arm and (group == "all" or r["case_type"] == group)]
            for metric in (*metrics, "action_correct", "failure_rate", "api_error_rate",
                           "followup_rate", "median_latency_ms", "p95_latency_ms"):
                if group == "all" and metric in (*metrics, "action_correct"):
                    continue
                if metric.endswith("_latency_ms"):
                    times = sorted(float(r["latency_ms"]) for r in subset)
                    value = statistics.median(times) if metric.startswith("median") else times[math.ceil(0.95 * len(times)) - 1]
                    emit(group, arm, metric, len(times), "", round(value, 2))
                    continue
                if metric in {"failure_rate", "api_error_rate", "followup_rate"}:
                    predicate = {
                        "failure_rate": lambda r: r["status"] != "ok" or bool(r["stop_reason"]),
                        "api_error_rate": lambda r: r["status"] != "ok",
                        "followup_rate": lambda r: int(r["followup_count"]) > 0,
                    }[metric]
                    values = [int(predicate(r)) for r in subset]
                else:
                    values = [int(r[metric]) for r in subset if r[metric] != "NA"]
                if values:
                    emit(group, arm, metric, len(values), sum(values), round(sum(values) / len(values), 4))
    write_csv(run_dir / "comparison.csv", summary)
    failures = []
    for row in rows:
        if row["status"] != "ok" or row["stop_reason"] or row["action_correct"] == "0" or any(
            row[metric] == "0" for metric in metrics
        ):
            if not row["failure_code"]:
                row["failure_code"] = "question_quality" if row["question_appropriate"] == "0" else "wrong_advice"
            failures.append(row)
    failure_path = run_dir / "failure_cases.csv"
    if failures:
        write_csv(failure_path, failures)
    else:
        with failure_path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerow(list(rows[0]))
    if chart:
        plot(run_dir, summary)


def plot(run_dir, summary):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    def get_value(group, arm, metric):
        return next(r for r in summary if (r["case_type"], r["arm"], r["metric"]) == (group, arm, metric))

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), layout="constrained")
    colors = ("#3D6785", "#087D79", "#694487")
    for ax, title, series in (
        (axes[0], "Clear supported items | same photo input", [
            ("Rules\nID", "clear_supported", ARMS[1], "identification_correct"),
            ("Baseline\nadvice", "clear_supported", ARMS[0], "advice_correct"),
            ("Rules\nadvice", "clear_supported", ARMS[1], "advice_correct"),
        ]),
        (axes[1], "Ambiguous items | user input reported separately", [
            ("Baseline\ninitial action", "ambiguous", ARMS[0], "action_correct"),
            ("Rules\ninitial action", "ambiguous", ARMS[1], "action_correct"),
            ("Rules + user\nfinal action", "ambiguous", ARMS[2], "action_correct"),
            ("Rules + user\nfinal advice", "ambiguous", ARMS[2], "advice_correct"),
        ]),
    ):
        entries = [get_value(*entry[1:]) for entry in series]
        bars = ax.bar(range(len(entries)), [r["value"] for r in entries],
                      color=[colors[ARMS.index(entry[2])] for entry in series], width=0.64)
        ax.bar_label(bars, labels=[f'{r["numerator"]}/{r["n"]}' for r in entries], padding=4)
        ax.set(ylim=(0, 1.14), title=title, ylabel="Proportion correct")
        ax.set_xticks(range(len(series)), [entry[0] for entry in series])
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(run_dir / "version_comparison.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Role E evaluation for LU Recycle Assistant")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("check")
    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--adapter", required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--baseline-revision", required=True)
    run_parser.add_argument("--improved-revision", required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--seed", type=int, default=521)
    for command in ("grade", "summarize"):
        command_parser = subcommands.add_parser(command)
        command_parser.add_argument("--out", type=Path, required=True)
        if command == "summarize":
            command_parser.add_argument("--no-chart", action="store_true")
    args = parser.parse_args()
    cases = manifest()
    validate(cases)
    if args.command in {"check", "run"}:
        photos, problems = check_photos(cases)
        if problems:
            print(f"References validated for {len(cases)} cases. Formal set needs {len(problems)} fixes.")
            print("\n".join(problems))
            return 1
        if args.command == "run":
            run(args, cases, photos)
        else:
            print(f"{len(photos)} photos passed preflight checks.")
    elif args.command == "grade":
        grade_sheet(args.out, cases)
    else:
        summarize(args.out, not args.no_chart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
