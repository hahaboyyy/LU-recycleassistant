import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from backend import DemoBackend, Request, Response, demo_cases, load_live_backend, load_rules


class DemoBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = DemoBackend(timeout_seconds=0.1)

    def request(self, case=None, **kwargs):
        return Request(b"fixture placeholder", "image/jpeg", demo_case=case, **kwargs)

    def test_supported_cases_resolve_to_a_rules(self):
        ids = {rule["item_id"] for rule in load_rules()["rules"]}
        found = set()
        for number in range(1, 17):
            case = f"DEV-{number:02d}"
            with self.subTest(case=case):
                response = self.backend.respond(self.request(case))
                self.assertEqual(response.status, "ready")
                self.assertIn(response.item_id, ids)
                found.add(response.item_id)
        self.assertEqual(found, ids)

    def test_development_bottle_clarification(self):
        question = self.backend.respond(self.request("DEV-17"))
        self.assertEqual(question.status, "question")
        self.assertEqual(question.options, ("Plastic", "Glass", "Not sure"))
        result = self.backend.respond(self.request("DEV-17", answers=((question.question, "Glass"),)))
        self.assertEqual(result, Response("ready", item_id="glass_beverage_bottle"))

    def test_development_cup_can_be_outside_scope(self):
        question = self.backend.respond(self.request("DEV-18"))
        result = self.backend.respond(self.request("DEV-18", answers=((question.question, "Paper"),)))
        self.assertEqual(result, Response("unsupported"))

    def test_two_questions_resolve_in_order(self):
        first = self.backend.respond(self.request("TWO_QUESTIONS"))
        answers = ((first.question, "Yes"),)
        second = self.backend.respond(self.request("TWO_QUESTIONS", answers=answers))
        self.assertEqual(second.status, "question")
        self.assertNotEqual(first.question, second.question)
        result = self.backend.respond(
            self.request("TWO_QUESTIONS", answers=answers + ((second.question, "Plastic"),))
        )
        self.assertEqual(result, Response("ready", item_id="plastic_beverage_bottle"))

    def test_uncertainty_is_not_a_confirmation(self):
        question = self.backend.respond(self.request("DEV-17"))
        result = self.backend.respond(
            self.request("DEV-17", answers=((question.question, "Not sure"),))
        )
        self.assertEqual(result.status, "question")
        self.assertIsNone(result.item_id)

    def test_out_of_scope_is_not_general_waste(self):
        for case in ("DEV-19", "DEV-20"):
            self.assertEqual(self.backend.respond(self.request(case)), Response("unsupported"))

    def test_explicit_correction_replaces_fixture_result(self):
        result = self.backend.respond(self.request("DEV-01", corrected_item_id="paper_tissue"))
        self.assertEqual(result, Response("ready", item_id="paper_tissue"))
        self.assertEqual(
            self.backend.respond(self.request("DEV-01", corrected_item_id="missing")),
            Response("unsupported"),
        )

    def test_arbitrary_upload_is_not_classified(self):
        self.assertEqual(self.backend.respond(self.request()), Response("unclear"))
        self.assertEqual(self.backend.respond(self.request("UNCLEAR")), Response("unclear"))

    def test_error_and_timeout_fixtures(self):
        with self.assertRaises(RuntimeError):
            self.backend.respond(self.request("ERROR"))
        with patch("backend.time.sleep") as sleep:
            self.assertEqual(self.backend.respond(self.request("TIMEOUT")), Response("unclear"))
            self.assertGreater(sleep.call_args.args[0], self.backend.timeout_seconds)

    def test_fixture_catalogue(self):
        expected = {f"DEV-{number:02d}" for number in range(1, 21)}
        expected.update({"UNCLEAR", "TWO_QUESTIONS", "ERROR", "TIMEOUT"})
        self.assertEqual(set(demo_cases()), expected)


class LiveBackendLoaderTests(unittest.TestCase):
    def test_factory_interface(self):
        module = ModuleType("test_role_d_factory")
        adapter = SimpleNamespace(respond=lambda request: Response("unclear"))
        module.build = lambda: adapter
        module.invalid = lambda: object()
        with patch.dict("sys.modules", {module.__name__: module}):
            self.assertIs(load_live_backend("test_role_d_factory:build"), adapter)
            with self.assertRaises(TypeError):
                load_live_backend("test_role_d_factory:invalid")
        with self.assertRaises(ValueError):
            load_live_backend("not-a-module-factory")


if __name__ == "__main__":
    unittest.main()
