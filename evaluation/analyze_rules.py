"""Run a local conformance check using scripted observations, never image predictions."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import pandas as pd

ROOT = Path(__file__).resolve().parent
INK = "#17293D"
BLUE = "#2A6992"
TEAL = "#087A70"
MUTED = "#5E6F7E"
RULES_SHA256 = "0481fe079e6a7b093ebc62f8e5bed68108ba3aa3f70ec8b7e70ec4db7e96dc75"

ROUTE = {
    ("beverage_bottle", "plastic", ""): "plastic_beverage_bottle",
    ("beverage_bottle", "glass", ""): "glass_beverage_bottle",
    ("drink_cup", "rigid_plastic", ""): "disposable_plastic_cup",
    ("drink_cup", "paper", ""): "paper_drink_cup",
    ("snack_packet", "", "metallic"): "foil_lined_snack_packet",
    ("metal_can", "", "food"): "metal_food_can",
    ("container", "glass", "food_jar"): "glass_food_jar",
}


def decide(rulebook, catalog, state, rounds):
    kind = state["kind"]
    material = state.get("material", "")
    detail = state.get("detail", "")
    if kind == "no_clear_object":
        return {"action": "no_clear_object", "advice": rulebook["no_clear_object"]}
    item_id = state.get("confirmed_item_id") or ROUTE.get((kind, material, detail))
    if item_id in catalog:
        rule = catalog[item_id]
        return {
            "action": "give_advice",
            "item_id": item_id,
            "route_id": rule["route_id"],
            "destination": rule["destination"],
            "advice": rule["disposal_advice"],
        }
    if item_id:
        return {"action": "out_of_scope", "advice": rulebook["unsupported_item"]}
    if rounds >= rulebook["max_clarification_rounds"]:
        return {"action": "unresolved_item", "advice": rulebook["unresolved_item"]}
    first = {
        "beverage_bottle": "material", "drink_cup": "material",
        "snack_packet": "lining", "metal_can": "package_type", "container": "material",
    }
    if not rounds:
        return {"action": "clarify_item", "question_key": first[kind]}
    if kind == "container":
        return {"action": "clarify_item", "question_key": "package_type"}
    if kind == "beverage_bottle":
        return {"action": "clarify_item", "question_key": "item_label"}
    return {"action": "unresolved_item", "advice": rulebook["unresolved_item"]}


def exercise(case, fixture, rulebook, catalog):
    state = dict(fixture["observation"])
    first = decide(rulebook, catalog, state, 0)
    response = first
    rounds = 0
    asked = [first["question_key"]] if "question_key" in first else []
    for reply in fixture["replies"]:
        if response.get("question_key") != reply["question_key"]:
            break
        rounds += 1
        state.update(reply["facts"])
        response = decide(rulebook, catalog, state, rounds)
        if "question_key" in response:
            asked.append(response["question_key"])
    initial_action_ok = first["action"] == case.expected_initial_action
    final_action_ok = response["action"] == case.expected_final_action
    first_question_ok = (first.get("question_key", "") == case.question_key_1) if case.question_key_1 else None
    item_ok = response.get("item_id", "") == case.expected_final_item_id
    route_ok = response.get("route_id", "") == case.expected_route_id
    destination_ok = response.get("destination", "") == case.expected_destination
    advice_ok = response.get("advice", "") == case.expected_final_advice
    rounds_ok = rounds == len(fixture["replies"]) <= rulebook["max_clarification_rounds"]
    checks = {
        "initial_action_ok": initial_action_ok, "final_action_ok": final_action_ok,
        "first_question_ok": first_question_ok, "item_id_ok": item_ok, "route_ok": route_ok,
        "destination_ok": destination_ok, "advice_text_ok": advice_ok, "rounds_ok": rounds_ok,
    }
    return {
        "case_id": case.case_id, "case_type": case.case_type,
        "expected_initial_action": case.expected_initial_action, "observed_initial_action": first["action"],
        "expected_final_action": case.expected_final_action, "observed_final_action": response["action"],
        "observed_item_id": response.get("item_id", ""), "observed_route_id": response.get("route_id", ""),
        "observed_destination": response.get("destination", ""), "observed_advice": response.get("advice", ""),
        "observed_questions": " | ".join(asked),
        "rounds": rounds,
        **checks,
        "all_checks_pass": all(ok for ok in checks.values() if ok is not None),
        "mismatched_checks": " | ".join(name for name, passed in checks.items() if passed is False),
    }


def chart(out, summary, actions):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
        "axes.labelcolor": MUTED, "axes.titlecolor": INK, "xtick.color": MUTED,
        "ytick.color": INK, "savefig.facecolor": "white",
    })
    fig, axes = plt.subplots(1, 2, figsize=(10.9, 4.05), gridspec_kw={"width_ratios": [1.15, 1]})
    left, right = axes
    labels = ["Clear supported", "Ambiguous", "Clear out of scope", "No clear object"]
    bars = left.barh(labels, summary["cases"], color=[BLUE, TEAL, "#839EB1", "#A9BAC6"], height=.48)
    left.bar_label(bars, padding=5, color=INK, fontweight="bold")
    left.set(xlim=(0, 61), xlabel="Cases")
    left.set_title("Test set composition", loc="left", fontweight="bold", pad=13)
    left.invert_yaxis()

    order = ["give_advice", "clarify_item", "out_of_scope", "no_clear_object", "unresolved_item"]
    labels = ["Give advice", "Ask a question", "Out of scope", "Request retake", "Still unresolved"]
    values = actions.set_index("action").reindex(order, fill_value=0)
    y = list(range(len(order)))
    first = right.barh([i-.16 for i in y], values["initial_cases"], height=.26, color=BLUE, label="First response")
    final = right.barh([i+.16 for i in y], values["final_cases"], height=.26, color=TEAL, label="Final response")
    for bars in (first, final):
        right.bar_label(bars, labels=[str(int(b.get_width())) if b.get_width() else "" for b in bars],
                        padding=4, color=INK, fontsize=9)
    right.set_yticks(y, labels)
    right.set(xlim=(0, 61), xlabel="Cases")
    right.set_title("Observed rule responses", loc="left", fontweight="bold", pad=13)
    right.invert_yaxis()
    right.legend(loc="lower right", frameon=False, fontsize=9)
    for ax in axes:
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#C6D2DC")
        ax.tick_params(axis="both", length=0, pad=5)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        ax.grid(axis="x", color="#E1E9EF", linewidth=.7)
        ax.set_axisbelow(True)
    fig.tight_layout(w_pad=3.2)
    fig.savefig(out / "rule_layer_analysis.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main(out):
    raw_rules = (ROOT / "data/rules_v1.json").read_bytes()
    if hashlib.sha256(raw_rules).hexdigest() != RULES_SHA256:
        raise ValueError("Rules v1.0.0 checksum mismatch")
    rulebook = json.loads(raw_rules)
    catalog = {rule["item_id"]: rule for rule in rulebook["rules"]}
    cases = pd.read_csv(ROOT / "data/formal_cases.csv", keep_default_na=False)
    fixtures = [json.loads(line) for line in (ROOT / "data/scripted_observations.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {fixture["case_id"]: fixture for fixture in fixtures}
    assert len(by_id) == len(fixtures) == len(cases) == cases.case_id.nunique() == 60
    results = pd.DataFrame(exercise(case, by_id[case.case_id], rulebook, catalog)
                           for case in cases.itertuples(index=False))
    kinds = ["clear_supported", "ambiguous", "clear_unsupported", "no_clear_object"]
    summary = (
        results.groupby("case_type").agg(cases=("case_id", "size"), initial_matches=("initial_action_ok", "sum"),
                                         final_matches=("final_action_ok", "sum"), fully_matching=("all_checks_pass", "sum"))
        .reindex(kinds).rename_axis("case_type").reset_index()
    )
    actions = pd.concat([
        results.observed_initial_action.value_counts().rename("initial_cases"),
        results.observed_final_action.value_counts().rename("final_cases"),
    ], axis=1).fillna(0).astype(int).rename_axis("action").reset_index()
    routes = (cases.query("expected_final_action == 'give_advice'")
              .groupby(["expected_route_id", "expected_destination_scope"], as_index=False)
              .agg(cases=("case_id", "size")))
    out.mkdir(parents=True, exist_ok=True)
    for name, df in {
        "rule_results": results, "summary_by_case_type": summary, "action_counts": actions,
        "route_coverage": routes, "rule_mismatches": results.loc[~results.all_checks_pass],
    }.items():
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")
    chart(out, summary, actions)
    print(summary.to_string(index=False))
    print(f"pandas {pd.__version__}; Matplotlib {matplotlib.__version__}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    main(parser.parse_args().out)
