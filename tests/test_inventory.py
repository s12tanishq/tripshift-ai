import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from tripshift.agent import AgentSession
from tripshift.core import load_scenario
from tripshift.inventory import IndiaTravelSearch, InventorySnapshot, assess_flight_offers

SCENARIO = Path(__file__).resolve().parents[1] / "data" / "nagpur_demo.json"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO)
        self.query = self.scenario.inventory_search

    def _client(self, flights=None, hotels=None, status=200):
        flights = flights if flights is not None else [self._flight()]
        hotels = hotels if hotels is not None else [self._hotel()]

        def handler(request):
            params = request.url.params
            self.assertEqual(params["api_key"], "test_search_key")
            self.assertEqual(params["gl"], "in")
            self.assertEqual(params["currency"], "INR")
            if status != 200:
                return httpx.Response(status, json={"error": "secret provider detail"})
            data = {"search_metadata": {"id": "search_123", "status": "Success", "created_at": "2026-10-01 05:42:48 UTC"}}
            if params["engine"] == "google_flights":
                self.assertEqual(params["departure_id"], "BOM")
                self.assertEqual(params["arrival_id"], "NAG")
                self.assertEqual(params["type"], "2")
                data["best_flights"] = flights
            else:
                self.assertEqual(params["engine"], "google_hotels")
                data["properties"] = hotels
            return httpx.Response(200, json=data)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def _flight(self):
        return {"price": 4800, "flights": [{"departure_airport": {"id": "BOM", "time": "2026-10-15 11:05"}, "arrival_airport": {"id": "NAG", "time": "2026-10-15 15:20"}, "airline": "Example Airways", "flight_number": "EA 101"}]}

    def _hotel(self):
        return {"type": "hotel", "name": "Example Hotel", "property_token": "hotel_1", "gps_coordinates": {"latitude": 21.15, "longitude": 79.09}, "total_rate": {"extracted_lowest": 3200}}

    def test_india_results_are_typed_and_flight_schedule_is_checked(self):
        with self._client() as client:
            adapter = IndiaTravelSearch("test_search_key", client)
            flights = adapter.search_flights(self.query.origin_iata, self.query.destination_iata, self.query.departure_date)
            hotels = adapter.search_hotels(self.query.hotel_latitude, self.query.hotel_longitude, self.query.hotel_check_in, self.query.hotel_check_out)
        self.assertEqual(flights.state, "offers_found")
        self.assertEqual(flights.mode, "indicative")
        self.assertEqual(flights.offers[0].operating_carriers, ("Example Airways",))
        self.assertIsNotNone(flights.provider_created_at)
        self.assertIsNone(flights.offers[0].expires_at)
        self.assertEqual(hotels.state, "offers_found")
        self.assertEqual(hotels.offers[0].name, "Example Hotel")
        checks = assess_flight_offers(self.scenario, 210, flights)
        self.assertTrue(checks[0].validation.valid)
        self.assertEqual(checks[0].validation.items["meeting"].status, "unaffected")

    def test_early_flight_is_conditional_on_moving_airport_pickup(self):
        flight = self._flight()
        flight["flights"][0]["departure_airport"]["time"] = "2026-10-15 08:05"
        flight["flights"][0]["arrival_airport"]["time"] = "2026-10-15 09:30"
        with self._client(flights=[flight]) as client:
            result = IndiaTravelSearch("test_search_key", client).search_flights(self.query.origin_iata, self.query.destination_iata, self.query.departure_date)
        check = assess_flight_offers(self.scenario, 210, result)[0]
        self.assertTrue(check.validation.valid)
        self.assertIn("driver confirmation required", check.condition)
        self.assertIn("10:00", check.condition)

    def test_empty_results_do_not_claim_global_unavailability(self):
        with self._client(flights=[]) as client:
            result = IndiaTravelSearch("test_search_key", client).search_flights(self.query.origin_iata, self.query.destination_iata, self.query.departure_date)
        self.assertEqual(result.state, "no_results")
        self.assertIn("elsewhere is unknown", result.message)

    def test_provider_error_is_unknown_and_does_not_expose_body(self):
        with self._client(status=403) as client:
            result = IndiaTravelSearch("test_search_key", client).search_hotels(self.query.hotel_latitude, self.query.hotel_longitude, self.query.hotel_check_in, self.query.hotel_check_out)
        self.assertEqual(result.state, "unknown")
        self.assertNotIn("secret provider detail", result.message)

    def test_outside_radius_is_not_presented_as_usable_hotel(self):
        hotel = self._hotel()
        hotel["gps_coordinates"] = {"latitude": 22.0, "longitude": 79.0}
        with self._client(hotels=[hotel]) as client:
            result = IndiaTravelSearch("test_search_key", client).search_hotels(self.query.hotel_latitude, self.query.hotel_longitude, self.query.hotel_check_in, self.query.hotel_check_out)
        self.assertEqual(result.state, "unknown")
        self.assertFalse(result.offers)

    def test_model_must_read_supplied_provider_evidence(self):
        with self._client() as client:
            adapter = IndiaTravelSearch("test_search_key", client)
            snapshot = InventorySnapshot(
                adapter.search_flights(self.query.origin_iata, self.query.destination_iata, self.query.departure_date),
                adapter.search_hotels(self.query.hotel_latitude, self.query.hotel_longitude, self.query.hotel_check_in, self.query.hotel_check_out),
            )
        session = AgentSession(self.scenario, set(), "fake", "fake-model", snapshot)
        self.assertIn("read provider evidence", session.missing_steps())
        result = session.call("read_provider_inventory", {})
        self.assertEqual(result["flights"]["offers"][0]["carrier"], "Example Airways")
        session.call("set_flight_delay", {"delay_minutes": 210})
        self.assertIn("validate provider flight timings", session.missing_steps())
        checks = session.call("validate_provider_flights", {})
        self.assertTrue(checks["checks"][0]["timing_valid"])
