"""Command-line entry point for the TripShift demo agent."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from tripshift.agent import run_trip_agent
from tripshift.core import load_scenario
from tripshift.inventory import IndiaTravelSearch, InventorySnapshot, assess_flight_offers


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a simulated travel disruption")
    parser.add_argument("disruption", nargs="?", default="Flight delayed by 3 hours 30 minutes")
    parser.add_argument("--delay", type=int, help="Explicit flight delay in minutes")
    parser.add_argument("--second-shock", action="store_true", help="Make the preferred replacement flight unavailable")
    parser.add_argument("--impossible", action="store_true", help="Make every scenario option unavailable")
    parser.add_argument("--provider", choices=["auto", "groq", "gemini"], default="auto")
    parser.add_argument("--search-offers", action="store_true", help="Search India-localized flight and hotel results before analysis")
    parser.add_argument("--inventory-only", action="store_true", help="Search provider evidence without calling a model")
    args = parser.parse_args()
    scenario = load_scenario(Path(__file__).parent / "data" / "nagpur_demo.json")
    inventory = None
    if args.search_offers or args.inventory_only:
        if scenario.inventory_search is None:
            parser.error("This scenario has no provider search configuration")
        load_dotenv(Path(__file__).parent / ".env", override=True)
        query = scenario.inventory_search
        client = IndiaTravelSearch(os.getenv("SERPAPI_API_KEY"))
        try:
            inventory = InventorySnapshot(
                client.search_flights(query.origin_iata, query.destination_iata, query.departure_date),
                client.search_hotels(query.hotel_latitude, query.hotel_longitude, query.hotel_check_in, query.hotel_check_out, query.hotel_radius_km),
            )
        finally:
            client.close()
        print(f"Provider flights: {inventory.flights.state} ({inventory.flights.mode}) — {inventory.flights.message}")
        print(f"Provider hotels:  {inventory.hotels.state} ({inventory.hotels.mode}) — {inventory.hotels.message}")
        if args.delay is not None:
            for row in assess_flight_offers(scenario, args.delay, inventory.flights):
                status = "conditional: earlier pickup requires driver confirmation" if row.condition else "fits known timing rules" if row.validation and row.validation.valid else "timing blocked" if row.validation else "not comparable"
                print(f"  {row.offer.id}: {status}; {row.offer.currency} {row.offer.amount}; indicative search result")
        if args.inventory_only:
            return
    request = f"The flight to Nagpur is delayed by {args.delay} minutes. Analyze and replan." if args.delay is not None else args.disruption
    unavailable = {"flight-a", "flight-b", "late-checkin"} if args.impossible else {"flight-b"} if args.second_shock else set()
    run = run_trip_agent(scenario, request, unavailable, args.provider, inventory=inventory)
    print(f"\nTripShift | {scenario.title} | {run.delay_minutes} min delay | {run.provider}/{run.model}")
    print("\nImpact:")
    for item in run.impact.items.values():
        print(f"  {item.title:22} {item.status:10} {item.start:%d %b %H:%M %Z}  {item.reason}")
    print("\nRecovery options:")
    for plan in run.plans:
        print(f"  {'VALID' if plan.valid else 'BLOCKED':7} {plan.title} | +₹{plan.cost_delta_inr:,} | {plan.arrival_delay_minutes} min arrival shift")
        for issue in plan.violations:
            print(f"           {issue}")
    print("\nSelected:", run.selected.title if run.selected else "No feasible plan")
    print("Fallback:", run.fallback.title if run.fallback else "None")
    print("\nAgent steps:")
    for event in run.trace:
        print(f"  {event.step:02d} {event.tool}: {event.detail}")


if __name__ == "__main__":
    main()
