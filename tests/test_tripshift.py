import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tripshift.agent import AgentSession, _run_provider
from tripshift.core import Dependency, Item, Scenario, evaluate, evaluate_all, load_scenario, parse_time, topological_order
from tripshift.inventory import InventorySnapshot, SearchResult

SCENARIO = Path(__file__).resolve().parents[1] / "data" / "nagpur_demo.json"


class FakeClient:
    """Scripted model responses that exercise the real tool-dispatch loop."""
    def __init__(self, steps):
        self.steps = iter(steps)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        step = next(self.steps)
        calls = [SimpleNamespace(id=f"call_{i}_{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)), model_extra={}) for i, (name, args) in enumerate(step)] if isinstance(step, list) else []
        message = SimpleNamespace(content="Analysis complete" if not calls else "", tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class TripShiftTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO)

    def test_baseline_is_feasible(self):
        report = evaluate(self.scenario)
        self.assertTrue(report.valid)
        self.assertFalse(report.violations)

    def test_delay_propagates_through_dependencies(self):
        report = evaluate(self.scenario, 210)
        self.assertFalse(report.valid)
        self.assertEqual(report.items["hotel"].status, "broken")
        self.assertEqual(report.items["meeting"].status, "broken")
        self.assertEqual(report.items["activity"].status, "at risk")
        self.assertEqual(report.items["meeting"].cause_path, ("Flight to Nagpur", "Airport transfer", "Hotel check-in", "Client meeting"))

    def test_recovery_plans_are_validated_and_ranked(self):
        reports = evaluate_all(self.scenario, 210)
        self.assertEqual(reports[0].plan_id, "lower_cost_flight")
        self.assertEqual(sum(row.valid for row in reports), 3)
        self.assertFalse(next(row for row in reports if row.plan_id == "no_change").valid)

    def test_no_change_is_best_when_delay_is_feasible(self):
        reports = evaluate_all(self.scenario, 0)
        self.assertEqual(reports[0].plan_id, "no_change")
        self.assertTrue(reports[0].valid)

    def test_model_tool_loop_selects_checked_plan_and_fallback(self):
        client = FakeClient([
            [("read_itinerary", {}), ("set_flight_delay", {"delay_minutes": 210})],
            [("analyze_dependencies", {}), ("search_recovery_options", {})],
            [("validate_recovery_options", {})],
            [("select_recovery", {"plan_id": "lower_cost_flight", "reason": "Preserves the meeting at lower cost"}), ("select_fallback", {"plan_id": "earlier_flight"})],
            [("prepare_messages", {})],
            "final",
        ])
        run = _run_provider(self.scenario, "Flight delayed by 210 minutes", set(), "fake", "fake-model", client, 8)
        self.assertEqual(run.selected.plan_id, "lower_cost_flight")
        self.assertEqual(run.fallback.plan_id, "earlier_flight")
        self.assertEqual(len(run.messages), 3)
        self.assertTrue(any(row.tool == "select_recovery" for row in run.trace))

    def test_model_reads_provider_snapshot_before_completing(self):
        now = datetime.now(timezone.utc)
        snapshot = InventorySnapshot(
            SearchResult("unknown", now, "test", (), "No flight response"),
            SearchResult("unknown", now, "test", (), "No hotel response"),
        )
        client = FakeClient([
            [("read_itinerary", {}), ("read_provider_inventory", {}), ("set_flight_delay", {"delay_minutes": 210})],
            [("analyze_dependencies", {}), ("search_recovery_options", {})],
            [("validate_recovery_options", {})],
            [("select_recovery", {"plan_id": "lower_cost_flight", "reason": "Checked"}), ("select_fallback", {"plan_id": "earlier_flight"})],
            [("prepare_messages", {})],
            "final",
        ])
        run = _run_provider(self.scenario, "Flight delayed by 210 minutes", set(), "fake", "fake-model", client, 8, snapshot)
        self.assertTrue(any(row.tool == "read_provider_inventory" for row in run.trace))

    def test_model_cannot_select_invalid_plan(self):
        session = AgentSession(self.scenario, set(), "fake", "fake-model")
        session.call("set_flight_delay", {"delay_minutes": 210})
        session.call("validate_recovery_options", {})
        result = session.call("select_recovery", {"plan_id": "no_change", "reason": "cheap"})
        self.assertIn("error", result)
        self.assertIsNone(session.selected)

    def test_model_cannot_finish_without_reading_journey_and_options(self):
        session = AgentSession(self.scenario, set(), "fake", "fake-model")
        session.call("set_flight_delay", {"delay_minutes": 210})
        session.call("analyze_dependencies", {})
        session.call("validate_recovery_options", {})
        session.call("select_recovery", {"plan_id": "lower_cost_flight", "reason": "Valid"})
        session.call("select_fallback", {"plan_id": "earlier_flight"})
        session.call("prepare_messages", {})
        self.assertIn("read the itinerary", session.missing_steps())
        self.assertIn("search recovery options", session.missing_steps())

    def test_second_shock_blocks_preferred_flight(self):
        session = AgentSession(self.scenario, {"flight-b"}, "fake", "fake-model")
        session.call("set_flight_delay", {"delay_minutes": 210})
        result = session.call("validate_recovery_options", {})
        blocked = next(row for row in result["plans"] if row["plan_id"] == "lower_cost_flight")
        self.assertFalse(blocked["valid"])
        self.assertIn("unavailable", blocked["violations"][-1])

    def test_impossible_case_reports_blockers(self):
        session = AgentSession(self.scenario, {"flight-a", "flight-b", "late-checkin"}, "fake", "fake-model")
        session.call("set_flight_delay", {"delay_minutes": 210})
        session.call("analyze_dependencies", {})
        session.call("validate_recovery_options", {})
        self.assertTrue(session.call("report_no_feasible_plan", {})["blocked"])
        self.assertEqual(session.call("prepare_messages", {})["drafts"][0]["recipient"], "Traveller")

    def test_time_math_remains_timezone_aware(self):
        report = evaluate(self.scenario, 210)
        self.assertIsNotNone(report.items["flight"].end.utcoffset())
        self.assertEqual(report.items["flight"].end - self.scenario.items["flight"].end, timedelta(minutes=210))

    def test_overnight_dependency_moves_into_next_day(self):
        flight = Item("flight", "flight", "Night flight", parse_time("2026-10-15T21:00:00+05:30"), parse_time("2026-10-15T23:50:00+05:30"), "Airport", False)
        transfer = Item("transfer", "transfer", "Transfer", parse_time("2026-10-16T00:20:00+05:30"), parse_time("2026-10-16T01:00:00+05:30"), "Hotel", True)
        scenario = Scenario("overnight", "Overnight", "Test fixture", {"flight": flight, "transfer": transfer}, (Dependency("flight", "transfer", 30, "Airport exit"),), "flight", 50, (), {})
        report = evaluate(scenario, 50)
        self.assertEqual(report.items["transfer"].start, parse_time("2026-10-16T01:10:00+05:30"))

    def test_dst_shift_uses_elapsed_minutes_and_valid_local_times(self):
        flight = Item("flight", "flight", "Flight", parse_time("2026-03-08T01:30:00-05:00", "America/New_York"), parse_time("2026-03-08T01:50:00-05:00", "America/New_York"), "Airport", False)
        transfer = Item("transfer", "transfer", "Pickup", parse_time("2026-03-08T03:30:00-04:00", "America/New_York"), parse_time("2026-03-08T04:00:00-04:00", "America/New_York"), "Hotel", True)
        scenario = Scenario("dst", "DST", "Test", {"flight": flight, "transfer": transfer}, (Dependency("flight", "transfer", 20, "Exit airport"),), "flight", 30, (), {}, "America/New_York")
        report = evaluate(scenario, 30)
        self.assertEqual(report.items["flight"].end.isoformat(), "2026-03-08T03:20:00-04:00")
        self.assertEqual(report.items["transfer"].start.isoformat(), "2026-03-08T03:40:00-04:00")
        self.assertEqual(report.arrival_delay_minutes, 30)

    def test_duration_across_fall_dst_is_elapsed_time(self):
        start = parse_time("2026-11-01T01:30:00-04:00", "America/New_York")
        end = parse_time("2026-11-01T01:30:00-05:00", "America/New_York")
        item = Item("flight", "flight", "Flight", start, end, "Airport", False)
        self.assertEqual(item.duration, timedelta(hours=1))

    def test_cross_zone_connection_keeps_destination_clock(self):
        flight = Item("flight", "flight", "Flight", parse_time("2026-10-15T10:00:00-04:00", "America/New_York"), parse_time("2026-10-15T22:00:00+01:00", "Europe/London"), "London Airport", False)
        transfer = Item("transfer", "transfer", "Pickup", parse_time("2026-10-15T22:30:00+01:00", "Europe/London"), parse_time("2026-10-15T23:00:00+01:00", "Europe/London"), "Hotel", True)
        scenario = Scenario("cross-zone", "Cross-zone", "Test", {"flight": flight, "transfer": transfer}, (Dependency("flight", "transfer", 30, "Border exit"),), "flight", 45, (), {})
        report = evaluate(scenario, 45)
        self.assertEqual(flight.duration, timedelta(hours=7))
        self.assertEqual(report.items["transfer"].start.isoformat(), "2026-10-15T23:15:00+01:00")
        self.assertEqual(report.items["transfer"].start.tzinfo.key, "Europe/London")

    def test_invalid_or_ambiguous_local_times_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Nonexistent"):
            parse_time("2026-03-08T02:30:00", "America/New_York")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            parse_time("2026-11-01T01:30:00", "America/New_York")
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_time("2026-03-08T03:30:00-05:00", "America/New_York")

    def test_maximum_connection_gap_blocks_stale_pickup(self):
        flight = Item("flight", "flight", "Flight", parse_time("2026-10-15T09:00:00+05:30"), parse_time("2026-10-15T10:00:00+05:30"), "Airport", False)
        transfer = Item("transfer", "transfer", "Pickup", parse_time("2026-10-15T11:31:00+05:30"), parse_time("2026-10-15T12:01:00+05:30"), "Hotel", True)
        scenario = Scenario("connection", "Connection", "Test", {"flight": flight, "transfer": transfer}, (Dependency("flight", "transfer", 30, "Exit airport", 60),), "flight", 0, (), {})
        report = evaluate(scenario)
        self.assertFalse(report.valid)
        self.assertIn("31 min after the maximum connection window", report.items["transfer"].reason)

    def test_hotel_start_and_end_windows_are_checked(self):
        hotel = Item("hotel", "hotel", "Hotel check-in", parse_time("2026-10-15T09:00:00+05:30"), parse_time("2026-10-15T09:30:00+05:30"), "Hotel", True, earliest_start=parse_time("2026-10-15T10:00:00+05:30"), latest_end=parse_time("2026-10-15T10:20:00+05:30"))
        scenario = Scenario("hotel", "Hotel", "Test", {"hotel": hotel}, (), "hotel", 0, (), {})
        report = evaluate(scenario)
        self.assertEqual(report.items["hotel"].start, parse_time("2026-10-15T10:00:00+05:30"))
        self.assertIn("10 min after its latest allowed end", report.items["hotel"].reason)

    def test_cycle_is_rejected(self):
        cycle = replace(self.scenario, dependencies=self.scenario.dependencies + (Dependency("activity", "flight", 0, "Bad edge"),))
        with self.assertRaisesRegex(ValueError, "cycle"):
            topological_order(cycle)


if __name__ == "__main__":
    unittest.main()
