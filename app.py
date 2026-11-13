import base64
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import monotonic
from uuid import uuid4

import streamlit as st
from backend import Request, Response, demo_cases, load_live_backend, load_rules
from integration import IntegratedBackend
from photo import sanitize_photo

ROOT = Path(__file__).resolve().parent
BACKEND_SPEC = os.getenv("RECYCLE_D_BACKEND", "").strip()
DEFAULT_TIMEOUT = 35.0 if BACKEND_SPEC else 8.0
try:
    TIMEOUT = min(120.0, max(1.0, float(os.getenv("RECYCLE_D_TIMEOUT", str(DEFAULT_TIMEOUT)))))
except ValueError:
    TIMEOUT = DEFAULT_TIMEOUT
RULES = load_rules()
ITEMS = {item["item_id"]: item for item in RULES["rules"]}
MAX_TURNS = min(2, RULES["max_clarification_rounds"])


@st.cache_resource
def resources():
    return ThreadPoolExecutor(max_workers=4), threading.BoundedSemaphore(8), threading.Lock()


def new_flow(serial=0, preferred_source=None):
    return {"serial": serial, "request": None, "response": None, "job": None,
            "error": None, "source": None, "run_id": None, "fallback": None,
            "correcting": False, "preferred_source": preferred_source}


def log_event(flow, status, elapsed_ms=None, response=None):
    path = os.getenv("RECYCLE_D_LOG_JSONL", "").strip()
    if not path or not flow["run_id"]:
        return
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": flow["run_id"], "mode": "live" if BACKEND_SPEC else "fixture",
        "input_source": flow["source"], "rules_version": RULES["rules_version"],
        "status": status, "elapsed_ms": elapsed_ms,
        "clarification_rounds": len(flow["request"].answers),
        "item_id": response.item_id if response and status == "ready" else None,
        "route_id": response.route_id if response else "",
        "source_ids": response.source_ids if response else (),
        "fallback_key": response.fallback_key if response else "",
        "confirmed_by": response.confirmed_by if response else "",
        "question_key": response.question_key if response else "",
    }
    try:
        with resources()[2]:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
    except OSError:
        st.session_state["log_warning"] = True


def call_backend(request):
    adapter = load_live_backend(BACKEND_SPEC) if BACKEND_SPEC else IntegratedBackend(fixture=True, timeout=TIMEOUT)
    return adapter.respond(request), monotonic()


def start_job(flow, request):
    flow.update(request=request, response=None, error=None, fallback=None, correcting=False)
    pool, slots, _ = resources()
    if not slots.acquire(blocking=False):
        flow["error"] = "The service is busy. Please wait a moment and retry."
        log_event(flow, "busy")
        return
    try:
        started = monotonic()
        future = pool.submit(call_backend, request)
    except RuntimeError:
        slots.release()
        flow["error"] = "The service could not start. Please retry."
        log_event(flow, "error")
        return
    future.add_done_callback(lambda _: slots.release())
    flow["job"] = (future, started)


def reset(preferred_source=None):
    flow = st.session_state["flow"]
    if flow["job"]:
        flow["job"][0].cancel()
    st.session_state["flow"] = new_flow(flow["serial"] + 1, preferred_source)


def take_response(flow, response):
    request = flow["request"]
    if not isinstance(response, Response) or response.status not in {"ready", "question", "unclear", "unsupported", "unresolved"}:
        raise ValueError("Invalid response type or status")
    if response.status == "ready":
        if response.item_id not in ITEMS:
            raise ValueError("Invalid confirmed item ID")
        if request.corrected_item_id and response.item_id != request.corrected_item_id:
            raise ValueError("Correction was not respected")
        if response.advice and response.advice != ITEMS[response.item_id]["disposal_advice"]:
            raise ValueError("Advice did not match the confirmed rule")
    elif response.status == "question":
        if not isinstance(response.question, str) or not response.question.strip() or len(response.question) > 400:
            raise ValueError("Invalid question")
        if not isinstance(response.options, tuple) or len(response.options) > 8 or any(
            not isinstance(option, str) or not option.strip() or len(option) > 100 for option in response.options
        ) or len(set(response.options)) != len(response.options):
            raise ValueError("Invalid question options")
        if len(request.answers) >= MAX_TURNS:
            flow["fallback"] = RULES["unresolved_item"]
            return "unresolved"
    flow["response"] = response
    return response.status


@st.fragment(run_every=0.4)
def wait_for_response():
    flow = st.session_state["flow"]
    job = flow["job"]
    if not job:
        st.rerun()
    future, started = job
    now = monotonic()
    if not future.done() and now - started < TIMEOUT:
        st.status("Checking your photo…" if BACKEND_SPEC else "Loading demo result…",
                  state="running", expanded=False)
        return
    flow["job"] = None
    try:
        if not future.done():
            future.cancel()
            raise TimeoutError
        response, finished = future.result()
        if finished - started > TIMEOUT:
            raise TimeoutError
        status = take_response(flow, response)
        log_event(flow, status, round((finished - started) * 1000), response)
    except TimeoutError:
        flow["error"] = "The request timed out. Please retry or start over."
        log_event(flow, "timeout", round((now - started) * 1000))
    except Exception:
        flow["error"] = "The service could not complete the request. Please retry or start over."
        log_event(flow, "error", round((now - started) * 1000))
    st.rerun()


def set_correction(visible):
    st.session_state["flow"]["correcting"] = visible


def correction(flow):
    with st.container(border=True, key="correction_panel"):
        st.subheader("Correct the item")
        item_id = st.selectbox("Select the correct item", list(ITEMS), index=None,
                               format_func=lambda key: ITEMS[key]["item_name"],
                               key=f"correction-{flow['serial']}")
        confirm, cancel = st.columns([1, 1], gap="small")
        if confirm.button("Confirm correction", type="primary", disabled=item_id is None,
                          key=f"confirm-correction-{flow['serial']}"):
            start_job(flow, replace(flow["request"], corrected_item_id=item_id))
            st.rerun()
        cancel.button("Cancel", on_click=set_correction, args=(False,), key=f"cancel-correction-{flow['serial']}")


def plain_label(text):
    return re.sub(r"([\\`*_\[\]<>!])", r"\\\1", text)


def render_header(flow):
    active = flow["request"] is not None
    response = flow["response"]
    asking = response is not None and response.status == "question"
    had_question = active and bool(flow["request"].answers)
    ready = response is not None and response.status == "ready"
    final = bool(flow["fallback"] or (response and response.status in {"ready", "unclear", "unsupported", "unresolved"}))
    stage = 3 if final else (2 if asking or had_question else 1)
    skipped = final and not had_question
    mascot_name, mascot_alt = "recycle-mascot.svg", "A friendly recycling robot with a bottle, a can and a carton"
    if stage == 2:
        mascot_name, mascot_alt = "recycle-mascot-question.svg", "A recycling robot with a question bubble"
    elif ready:
        mascot_name, mascot_alt = "recycle-mascot-advice.svg", "A recycling robot showing a recycling sign"
    mascot = base64.b64encode((ROOT / "assets" / mascot_name).read_bytes()).decode("ascii")
    st.html(f"""
      <header class="lu-hero{' lu-compact' if active else ''}">
        <div class="lu-hero-copy">
          <span class="lu-campus">Lingnan University</span>
          <h1>LU Recycle Assistant</h1>
          <p>One photo. A clearer way to sort everyday waste on campus.</p>
          <div class="lu-pills">
            <span class="lu-pill">{len(ITEMS)} supported items</span>
            <span class="lu-pill">One item per photo</span>
          </div>
        </div>
        <img class="lu-mascot" src="data:image/svg+xml;base64,{mascot}"
             alt="{mascot_alt}">
      </header>
    """)
    steps = []
    for number, (title, detail) in enumerate((
        ("Photo", "Upload or take a picture"),
        ("Confirm", "Not needed for this result" if skipped else "Check the item if asked"),
        ("Advice", "See what to do next"),
    ), 1):
        if number == 2 and skipped:
            state = ' class="lu-step-skipped"'
        elif number == stage:
            state = ' aria-current="step"'
        else:
            state = ' class="lu-done"' if number < stage else ""
        note = ""
        if number == 2 and (skipped or stage == 1):
            note = f'<span class="lu-step-state">{"Skipped" if skipped else "Optional"}</span>'
        steps.append(f'<li{state}><span class="lu-step-number">{number}</span>'
                     f'<span><span class="lu-step-name">{title}</span>{note}'
                     f'<span class="lu-step-detail">{detail}</span></span></li>')
    st.html('<ol class="lu-steps" aria-label="Recycling workflow">' + "".join(steps) + '</ol>')


def render_input(flow):
    controls, preview = st.columns([1.05, .95], gap="medium")
    with controls.container(border=True, key="photo_controls"):
        st.subheader("Add a photo")
        sources = ["Upload photo", "Camera"] if BACKEND_SPEC else ["Demo photo", "Upload photo", "Camera"]
        preferred = flow.get("preferred_source")
        with st.container(key="source_picker_live" if BACKEND_SPEC else "source_picker_demo"):
            source = st.radio("Photo source", sources, horizontal=True,
                              index=sources.index(preferred) if preferred in sources else 0,
                              key=f"source-{flow['serial']}")
        scenario = None
        if not BACKEND_SPEC:
            scenarios = demo_cases()
            scenario = st.selectbox("Demo scenario", list(scenarios),
                                    format_func=lambda key: f"{key} — {scenarios[key]}",
                                    key=f"scenario-{flow['serial']}")
        raw = None
        if source == "Demo photo":
            photo_id = scenario if scenario and scenario.startswith("DEV-") else "DEV-17"
            path = ROOT / "data" / "development_photos" / f"{photo_id}.jpg"
            if path.is_file():
                raw = path.read_bytes()
            else:
                st.error("The selected development photo is missing.")
        elif source == "Upload photo":
            uploaded = st.file_uploader("Upload one photo", type=["jpg", "jpeg", "png", "webp"],
                                        key=f"upload-{flow['serial']}")
            raw = uploaded.getvalue() if uploaded else None
        else:
            st.caption("Allow camera access when your browser asks. If the camera is unavailable, use Upload photo.")
            photo = st.camera_input("Take a photo", key=f"camera-{flow['serial']}")
            raw = photo.getvalue() if photo else None

        clean = None
        if raw:
            try:
                clean = sanitize_photo(raw)
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Identify item", type="primary", disabled=clean is None, width="stretch",
                     key=f"identify-{flow['serial']}"):
            flow.update(run_id=uuid4().hex, source=source)
            start_job(flow, Request(image=clean, mime_type="image/jpeg", demo_case=scenario))
            st.rerun()
    with preview.container(border=True, key="photo_preview"):
        st.html('<p class="lu-preview-kicker">Preview</p>')
        if clean:
            st.image(clean, width="stretch", caption="Photo preview")
        else:
            st.html('''<div class="lu-empty-photo">
                <svg width="36" height="30" viewBox="0 0 36 30" fill="none" stroke="currentColor"
                     stroke-width="2" aria-hidden="true"><rect x="2" y="3" width="32" height="24" rx="5"/>
                     <circle cx="12" cy="11" r="2.5"/><path d="m5 24 8-7 5 4 5-6 8 9"/></svg>
                <strong>No photo yet</strong><span>Your image will appear here.</span></div>''')
        st.caption("Show one item clearly.")


def render_interaction(flow):
    if flow["job"]:
        wait_for_response()
        return
    response = flow["response"]
    ready = response is not None and response.status == "ready"
    correcting = flow.get("correcting", False)
    if correcting and not ready:
        correction(flow)
        return
    if flow["error"]:
        st.error(flow["error"])
        if st.button("Retry", type="primary", key=f"retry-{flow['serial']}"):
            start_job(flow, flow["request"])
            st.rerun()
    elif flow["fallback"]:
        st.warning(flow["fallback"])
        st.button("Take another photo", type="primary", on_click=reset, args=(flow["source"],))
    elif ready:
        item = ITEMS[response.item_id]
        with st.container(border=True, key="advice_card"):
            with st.container(key="identification_section"):
                name, action = st.columns([3.7, 1.3], gap="small", vertical_alignment="center")
                item_name = escape(f"{item['item_name']} — {item['material']}")
                name.html(f'<div class="lu-id-copy"><p class="lu-field-label">Identification</p>'
                          f'<p class="lu-item-name">{item_name}</p></div>')
                if not correcting:
                    action.button("Wrong item?", on_click=set_correction, args=(True,),
                                  key=f"wrong-item-{flow['serial']}")
            with st.container(key="disposal_section"):
                advice = escape(response.advice or item["disposal_advice"])
                st.html(f'<div class="lu-advice-copy"><p class="lu-field-label">Disposal Advice</p>'
                        f'<p class="lu-advice-text">{advice}</p></div>')
        with st.expander("Why this advice?"):
            basis = {
                "model": "The photo recognition matched this supported item.",
                "user_answer": "Your clarification confirmed this item.",
                "correction": "You selected this item using the correction control.",
            }
            st.write(basis.get(response.confirmed_by, "This item matches the campus guide."))
            st.write(f"Destination: {item['destination']}")
            st.caption(f"Rules {RULES['rules_version']} · {response.item_id}")
        if not correcting:
            st.button("Sort another item", type="primary", on_click=reset, args=(flow["source"],),
                      key=f"sort-next-{flow['serial']}")
    elif response and response.status == "question":
        with st.container(border=True, key="question_panel"):
            request = flow["request"]
            turn = len(request.answers) + 1
            st.subheader(f"Clarification {turn} of {MAX_TURNS}")
            st.text(response.question)
            with st.form(f"question-{flow['serial']}-{turn}"):
                if response.options:
                    answer = st.radio("Your answer", response.options, index=None, format_func=plain_label,
                                      key=f"answer-{flow['serial']}-{turn}")
                else:
                    answer = st.text_input("Your answer", max_chars=160, key=f"answer-{flow['serial']}-{turn}")
                if st.form_submit_button("Submit answer", type="primary"):
                    if answer and answer.strip():
                        start_job(flow, replace(
                            request, answers=request.answers + ((response.question, answer.strip()),),
                            recognition=response.recognition,
                        ))
                        st.rerun()
                    else:
                        st.warning("Choose or enter an answer to continue.")
    elif response and response.status == "unclear":
        st.warning(RULES["no_clear_object"])
        st.button("Take another photo", type="primary", on_click=reset, args=(flow["source"],))
    elif response and response.status == "unsupported":
        if response.identification:
            st.markdown("**Identification**")
            st.text(response.identification)
        st.warning(RULES["unsupported_item"])
        st.button("Take another photo", type="primary", on_click=reset, args=(flow["source"],))
    elif response and response.status == "unresolved":
        st.warning(RULES["unresolved_item"])
        st.button("Take another photo", type="primary", on_click=reset, args=(flow["source"],))
    if correcting:
        correction(flow)
    elif not ready:
        st.button("Wrong item?", on_click=set_correction, args=(True,), key=f"wrong-item-{flow['serial']}")


st.set_page_config(page_title="LU Recycle Assistant", page_icon="♻️", layout="wide")
st.html(str(ROOT / "assets" / "interface.css"))
if "flow" not in st.session_state:
    st.session_state["flow"] = new_flow()
flow = st.session_state["flow"]
render_header(flow)
if not BACKEND_SPEC:
    st.html('<aside class="lu-demo-mode"><strong>Demo mode</strong>'
            '<span>Scripted recognition responses · Choose a development scenario to explore the workflow.</span></aside>')
if st.session_state.get("log_warning"):
    st.warning("The optional run log could not be written.")

if flow["request"] is None:
    render_input(flow)
else:
    preview, actions = st.columns([.7, 1.3], gap="medium")
    with preview.container(border=True, key="answer_preview"):
        st.html('<p class="lu-preview-kicker">Current photo</p>')
        st.image(flow["request"].image, width="stretch", caption="Photo preview")
        if not (flow["response"] and flow["response"].status == "ready"):
            st.button("Start over", on_click=reset, key=f"start-over-{flow['serial']}")
    with actions:
        render_interaction(flow)

st.html('<footer class="lu-footer">LU campus recycling project · Guidance for supported items</footer>')
