import time

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


def wait_for(app, ready, seconds=5):
    deadline = time.monotonic() + seconds
    while not ready() and time.monotonic() < deadline:
        time.sleep(0.1)
        app.run()
    assert not app.exception
    assert ready()


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def has_text(app, fragment):
    text = [element.value for element in (*app.markdown, *app.subheader, *app.warning, *app.error)]
    text.extend(element.proto.body for element in app.get("html"))
    return any(fragment in value for value in text)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("RECYCLE_D_BACKEND", raising=False)
    monkeypatch.setenv("RECYCLE_D_TIMEOUT", "1")
    # AppTest polls complete runs. The browser check covers the timed status fragment.
    monkeypatch.setattr(st, "fragment", lambda **kwargs: lambda function: function)
    return AppTest.from_file("app.py", default_timeout=6).run()


def start_case(app, case):
    app.selectbox[0].set_value(case).run()
    button(app, "Identify item").click().run()


def answer(app, choice):
    app.radio[0].set_value(choice)
    button(app, "Submit answer").click().run()


def test_page_direct_advice(app):
    start_case(app, "DEV-01")
    wait_for(app, lambda: has_text(app, "Plastic beverage bottle"))
    assert has_text(app, "Disposal Advice")
    # The browser acceptance exercises correction and restart callbacks.
    assert any(widget.label == "Wrong item?" for widget in app.button)


def test_page_clarification_resolves(app):
    start_case(app, "DEV-17")
    wait_for(app, lambda: has_text(app, "Clarification 1 of 2"))
    answer(app, "Glass")
    wait_for(app, lambda: has_text(app, "Glass beverage bottle"))


def test_page_limits_clarification_to_two_rounds(app):
    start_case(app, "TWO_QUESTIONS")
    wait_for(app, lambda: has_text(app, "Clarification 1 of 2"))
    answer(app, "Not sure")
    wait_for(app, lambda: has_text(app, "Clarification 2 of 2"))
    answer(app, "Not sure")
    wait_for(app, lambda: has_text(app, "I could not confirm the item"))


@pytest.mark.parametrize(("case", "message"), [
    ("DEV-19", "outside the current guide"),
    ("UNCLEAR", "Please retake the photo"),
    ("ERROR", "could not complete the request"),
    ("TIMEOUT", "The request timed out"),
])
def test_page_fallbacks(app, case, message):
    start_case(app, case)
    wait_for(app, lambda: has_text(app, message))
