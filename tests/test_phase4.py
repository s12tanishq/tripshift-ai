"""Behavior checks for portable setups and actionable failure states."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tripshift.agent import AgentWorkflowError, run_trip_agent
from tripshift.core import load_scenario
from tripshift.inventory import SearchResult, search_guidance
from tripshift.scenario_io import SavedSetup, load_setup, save_setup

SCENARIO = Path(__file__).resolve().parents[1] / "data" / "nagpur_demo.json"


class Phase4Tests(unittest.TestCase):
    def test_saved_setup_round_trip_contains_inputs_only(self):
        setup = SavedSetup("Client visit", 210, "Flight delayed by 3.5 hours", "Second shock: chosen flight unavailable", "Gemini")
        payload = save_setup(setup)
        self.assertEqual(load_setup(payload), setup)
        self.assertNotIn(b"API_KEY", payload)
        self.assertNotIn(b"inventory", payload)
        self.assertNotIn(b"messages", payload)

    def test_saved_setup_rejects_wrong_journey_and_invalid_values(self):
        data = json.loads(save_setup(SavedSetup("Demo", 210, "", "Normal", "Auto")))
        data["scenario_id"] = "other-journey"
        with self.assertRaisesRegex(ValueError, "different journey"):
            load_setup(json.dumps(data).encode())
        data["scenario_id"] = "nagpur-demo"
        data["delay_minutes"] = 999
        with self.assertRaisesRegex(ValueError, "Delay"):
            load_setup(json.dumps(data).encode())
        with self.assertRaisesRegex(ValueError, "too large"):
            load_setup(b" " * 1_048_577)

    def test_travel_search_guidance_distinguishes_failure_and_staleness(self):
        now = datetime.now(timezone.utc)
        missing = SearchResult("unknown", now, "indicative", (), "missing", issue_code="missing_key")
        quota = SearchResult("unknown", now, "indicative", (), "quota", issue_code="quota")
        stale = SearchResult("offers_found", now - timedelta(minutes=40), "indicative", ("result",), "found")
        fresh = SearchResult("offers_found", now, "indicative", ("result",), "found")
        self.assertIn("SERPAPI_API_KEY", search_guidance(missing, now))
        self.assertIn("allowance", search_guidance(quota, now))
        self.assertIn("over 30 minutes", search_guidance(stale, now))
        self.assertIsNone(search_guidance(fresh, now))

    def test_dashboard_clears_analysis_when_inputs_change(self):
        app = AppTest.from_file(str(SCENARIO.parents[1] / "app.py"), default_timeout=30).run()
        app.session_state["run"] = "old analysis"
        app.session_state["run_inputs"] = (210, "", "Normal", "Auto")
        app.slider[0].set_value(225).run()
        self.assertIsNone(app.session_state.get("run"))
        self.assertTrue(any("Inputs changed" in row.value for row in app.info))
        self.assertFalse(app.exception)

    def test_model_key_failure_has_specific_next_step(self):
        scenario = load_scenario(SCENARIO)
        with patch("tripshift.agent.load_dotenv"), patch("tripshift.agent.os.getenv", return_value=None):
            with self.assertRaises(AgentWorkflowError) as captured:
                run_trip_agent(scenario, "Flight delayed by 210 minutes", provider="gemini")
        self.assertIn("GEMINI_API_KEY", captured.exception.recovery_hint)
