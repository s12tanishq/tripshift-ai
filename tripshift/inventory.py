"""Read-only, India-localized travel search evidence; never booking inventory."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from typing import Any, Generic, Literal, TypeVar

import httpx

from .core import Plan, Scenario, Validation, evaluate, parse_time

T = TypeVar("T")
EvidenceState = Literal["offers_found", "no_results", "unknown"]


@dataclass(frozen=True)
class FlightOffer:
    id: str
    departure: datetime
    arrival: datetime
    origin: str
    destination: str
    operating_carriers: tuple[str, ...]
    connections: int
    amount: Decimal
    currency: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class HotelOffer:
    id: str
    name: str
    check_in_date: date
    check_out_date: date
    amount: Decimal
    currency: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class SearchResult(Generic[T]):
    state: EvidenceState
    observed_at: datetime
    mode: str
    offers: tuple[T, ...]
    message: str
    request_id: str | None = None
    provider_created_at: datetime | None = None


@dataclass(frozen=True)
class InventorySnapshot:
    flights: SearchResult[FlightOffer]
    hotels: SearchResult[HotelOffer]

    def for_agent(self) -> dict[str, Any]:
        return {
            "caution": "Indicative Google Travel search via SerpApi, not supplier inventory or a booking guarantee. Prices may change. No result is mapped to a simulated plan ID. Hotel results do not confirm late check-in at an existing booking.",
            "flights": {
                "state": self.flights.state, "mode": self.flights.mode,
                "observed_at": self.flights.observed_at.isoformat(),
                "provider_created_at": self.flights.provider_created_at.isoformat() if self.flights.provider_created_at else None,
                "message": self.flights.message,
                "offers": [{"id": row.id, "departure": row.departure.isoformat(), "arrival": row.arrival.isoformat(), "carrier": ", ".join(row.operating_carriers), "connections": row.connections, "amount": str(row.amount), "currency": row.currency, "expires_at": None} for row in self.flights.offers[:5]],
            },
            "hotels": {
                "state": self.hotels.state, "mode": self.hotels.mode,
                "observed_at": self.hotels.observed_at.isoformat(),
                "provider_created_at": self.hotels.provider_created_at.isoformat() if self.hotels.provider_created_at else None,
                "message": self.hotels.message,
                "offers": [{"id": row.id, "name": row.name, "check_in_date": row.check_in_date.isoformat(), "check_out_date": row.check_out_date.isoformat(), "amount": str(row.amount), "currency": row.currency, "expires_at": None} for row in self.hotels.offers[:5]],
            },
        }


@dataclass(frozen=True)
class FlightAssessment:
    offer: FlightOffer
    validation: Validation | None
    issue: str = ""
    condition: str = ""


def _money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid search price") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid search price")
    return result


def _created_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return parse_time(raw.replace(" UTC", "+00:00").replace("Z", "+00:00"))
    except ValueError:
        return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a = sin(radians(lat2-lat1)/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(radians(lon2-lon1)/2)**2
    return 6371 * 2 * asin(sqrt(a))


def _parse_flight(raw: dict[str, Any], origin: str, destination: str) -> FlightOffer:
    segments = raw["flights"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("Missing flight segments")
    first, last = segments[0], segments[-1]
    if first["departure_airport"]["id"] != origin or last["arrival_airport"]["id"] != destination:
        raise ValueError("Route mismatch")
    # This adapter is deliberately limited to the Indian domestic demo route.
    departure = parse_time(first["departure_airport"]["time"].replace(" ", "T"), "Asia/Kolkata")
    arrival = parse_time(last["arrival_airport"]["time"].replace(" ", "T"), "Asia/Kolkata")
    if departure is None or arrival is None or arrival <= departure:
        raise ValueError("Invalid flight schedule")
    carriers = tuple(dict.fromkeys(str(segment["airline"]) for segment in segments))
    if any(not carrier for carrier in carriers):
        raise ValueError("Missing airline")
    flight_ids = ":".join(str(segment["flight_number"]) for segment in segments)
    offer_id = sha256(f"{flight_ids}:{departure.isoformat()}".encode()).hexdigest()[:16]
    return FlightOffer(offer_id, departure, arrival, origin, destination, carriers, len(segments)-1, _money(raw["price"]), "INR")


def _parse_hotel(raw: dict[str, Any], check_in: date, check_out: date, latitude: float, longitude: float, radius_km: int) -> HotelOffer:
    if raw.get("type", "hotel") != "hotel":
        raise ValueError("Not a hotel")
    gps = raw["gps_coordinates"]
    if _distance_km(latitude, longitude, float(gps["latitude"]), float(gps["longitude"])) > radius_km:
        raise ValueError("Outside search radius")
    name = str(raw["name"])
    if not name:
        raise ValueError("Missing hotel name")
    amount = _money(raw["total_rate"]["extracted_lowest"])
    offer_id = str(raw["property_token"])
    return HotelOffer(offer_id, name, check_in, check_out, amount, "INR")


class IndiaTravelSearch:
    """SerpApi Google Flights/Hotels searches in India; no booking operation."""

    def __init__(self, key: str | None, client: Any | None = None):
        self.key = key or ""
        self.client = client or httpx.Client(timeout=35)
        self._owns_client = client is None
        self.mode = "indicative"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, params: dict[str, Any]) -> tuple[dict[str, Any], str | None, datetime | None]:
        response = self.client.get("https://serpapi.com/search.json", params={**params, "api_key": self.key})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid search response")
        metadata = data.get("search_metadata") or {}
        if data.get("error") or metadata.get("status") != "Success":
            raise ValueError("Search provider did not complete the query")
        return data, metadata.get("id"), _created_at(metadata.get("created_at"))

    def _unknown(self, now: datetime, message: str) -> SearchResult[Any]:
        return SearchResult("unknown", now, self.mode, (), message)

    def search_flights(self, origin: str, destination: str, departure_date: date, max_offers: int = 8) -> SearchResult[FlightOffer]:
        now = datetime.now(timezone.utc)
        if not self.key:
            return self._unknown(now, "SERPAPI_API_KEY is not configured")
        if (origin, destination) != ("BOM", "NAG"):
            return self._unknown(now, "This adapter currently supports the BOM to NAG India demo route")
        try:
            data, request_id, created = self._get({"engine": "google_flights", "departure_id": origin, "arrival_id": destination, "outbound_date": departure_date.isoformat(), "type": 2, "gl": "in", "hl": "en", "currency": "INR", "adults": 1})
            raw = (data.get("best_flights") or []) + (data.get("other_flights") or [])
            if not isinstance(raw, list):
                raise ValueError("Malformed flight search results")
            offers = []
            for item in raw:
                try:
                    offers.append(_parse_flight(item, origin, destination))
                except (KeyError, TypeError, ValueError):
                    continue
            if raw and not offers:
                return self._unknown(now, "Flight results were returned but could not be safely interpreted")
            offers.sort(key=lambda row: (row.arrival, row.amount))
            state: EvidenceState = "offers_found" if offers else "no_results"
            msg = f"{len(offers)} indicative flight result(s)" if offers else "No results for this search; availability elsewhere is unknown"
            return SearchResult(state, now, self.mode, tuple(offers[:max_offers]), msg, request_id, created)
        except httpx.HTTPStatusError as exc:
            return self._unknown(now, "Search quota reached" if exc.response.status_code == 429 else "Search key was rejected" if exc.response.status_code in (401, 403) else f"Flight search failed (HTTP {exc.response.status_code})")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return self._unknown(now, "Flight search could not be completed")

    def search_hotels(self, latitude: float, longitude: float, check_in: date, check_out: date, radius_km: int = 5, max_offers: int = 8) -> SearchResult[HotelOffer]:
        now = datetime.now(timezone.utc)
        if not self.key:
            return self._unknown(now, "SERPAPI_API_KEY is not configured")
        try:
            data, request_id, created = self._get({"engine": "google_hotels", "q": f"Hotels near {latitude},{longitude}, Nagpur, India", "check_in_date": check_in.isoformat(), "check_out_date": check_out.isoformat(), "adults": 1, "gl": "in", "hl": "en", "currency": "INR"})
            raw = data.get("properties") or []
            if not isinstance(raw, list):
                raise ValueError("Malformed hotel search results")
            offers = []
            for item in raw:
                try:
                    offers.append(_parse_hotel(item, check_in, check_out, latitude, longitude, radius_km))
                except (KeyError, TypeError, ValueError):
                    continue
            if raw and not offers:
                return self._unknown(now, "Hotel results were returned, but none had a verified location and total INR rate inside the search radius")
            offers.sort(key=lambda row: row.amount)
            state: EvidenceState = "offers_found" if offers else "no_results"
            msg = f"{len(offers)} indicative hotel result(s) within {radius_km} km" if offers else "No results for this search; availability elsewhere is unknown"
            return SearchResult(state, now, self.mode, tuple(offers[:max_offers]), msg, request_id, created)
        except httpx.HTTPStatusError as exc:
            return self._unknown(now, "Search quota reached" if exc.response.status_code == 429 else "Search key was rejected" if exc.response.status_code in (401, 403) else f"Hotel search failed (HTTP {exc.response.status_code})")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return self._unknown(now, "Hotel search could not be completed")


def assess_flight_offers(scenario: Scenario, delay_minutes: int, result: SearchResult[FlightOffer]) -> tuple[FlightAssessment, ...]:
    """Check travel timing, then try an explicitly conditional pickup change for early flights."""
    rows = []
    original_flight = scenario.items[scenario.disruption_item]
    pickup_dep = next((dep for dep in scenario.dependencies if dep.source == scenario.disruption_item and scenario.items[dep.target].kind == "transfer" and dep.max_gap_minutes is not None), None)
    for offer in result.offers:
        if offer.expires_at and offer.expires_at <= datetime.now(timezone.utc):
            rows.append(FlightAssessment(offer, None, "Search result expired; search again"))
            continue
        changes = {scenario.disruption_item: {"start": offer.departure.isoformat(), "end": offer.arrival.isoformat()}}
        plan = Plan(
            id=f"search:{offer.id}", title=f"Search flight: {', '.join(offer.operating_carriers)}",
            summary="Timing check only; price and rebooking terms are unconfirmed",
            cost_delta_inr=0, changes=changes, requires_option="",
        )
        try:
            validation = evaluate(scenario, delay_minutes, plan)
            condition = ""
            if not validation.valid and pickup_dep and offer.arrival < original_flight.end:
                transfer = scenario.items[pickup_dep.target]
                if transfer.movable:
                    pickup_start = (offer.arrival.astimezone(timezone.utc) + timedelta(minutes=pickup_dep.min_gap_minutes)).astimezone(transfer.start.tzinfo)
                    pickup_end = (pickup_start.astimezone(timezone.utc) + transfer.duration).astimezone(transfer.end.tzinfo)
                    revised = Plan(
                        id=f"search:{offer.id}:pickup", title=plan.title,
                        summary="Timing check assumes an earlier airport pickup; driver change is unconfirmed",
                        cost_delta_inr=0,
                        changes={**changes, transfer.id: {"start": pickup_start.isoformat(), "end": pickup_end.isoformat()}},
                        requires_option="",
                    )
                    alternative = evaluate(scenario, delay_minutes, revised)
                    if alternative.valid:
                        validation = alternative
                        condition = f"Timing fits only if airport pickup moves to {pickup_start:%H:%M %Z}; driver confirmation required"
            rows.append(FlightAssessment(offer, validation, condition=condition))
        except ValueError as exc:
            rows.append(FlightAssessment(offer, None, f"Could not compare result with journey: {exc}"))
    return tuple(rows)
