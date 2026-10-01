"""Deterministic trip simulation and plan validation. No model is trusted with time math."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _minutes_between(later: datetime, earlier: datetime) -> int:
    return int((_utc(later) - _utc(earlier)).total_seconds() // 60)


def _add_elapsed(value: datetime, elapsed: timedelta) -> datetime:
    return (_utc(value) + elapsed).astimezone(value.tzinfo)


def parse_time(value: str | None, timezone_name: str | None = None) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(value)
    if timezone_name:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {timezone_name}") from exc
        if result.tzinfo is None:
            candidates = []
            for fold in (0, 1):
                candidate = result.replace(tzinfo=zone, fold=fold)
                round_trip = _utc(candidate).astimezone(zone)
                if round_trip.replace(tzinfo=None) == result and round_trip.fold == fold:
                    candidates.append(candidate)
            if not candidates:
                raise ValueError(f"Nonexistent local time in {timezone_name}: {value}")
            if len(candidates) > 1:
                raise ValueError(f"Ambiguous local time in {timezone_name}; supply a UTC offset: {value}")
            return candidates[0]
        zoned = _utc(result).astimezone(zone)
        if result.utcoffset() != zoned.utcoffset():
            raise ValueError(f"UTC offset does not match {timezone_name}: {value}")
        return zoned
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"Timezone offset required: {value}")
    return result


def _same_instant(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _utc(left) == _utc(right)


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    title: str
    start: datetime
    end: datetime
    location: str
    movable: bool
    latest_start: datetime | None = None
    earliest_start: datetime | None = None
    latest_end: datetime | None = None

    @property
    def duration(self) -> timedelta:
        return _utc(self.end) - _utc(self.start)


@dataclass(frozen=True)
class Dependency:
    source: str
    target: str
    min_gap_minutes: int
    reason: str
    max_gap_minutes: int | None = None


@dataclass(frozen=True)
class Plan:
    id: str
    title: str
    summary: str
    cost_delta_inr: int
    changes: dict[str, dict[str, str]]
    requires_option: str


@dataclass(frozen=True)
class InventorySearch:
    origin_iata: str
    destination_iata: str
    departure_date: date
    hotel_latitude: float
    hotel_longitude: float
    hotel_check_in: date
    hotel_check_out: date
    hotel_radius_km: int = 5


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    source: str
    items: dict[str, Item]
    dependencies: tuple[Dependency, ...]
    disruption_item: str
    default_delay_minutes: int
    plans: tuple[Plan, ...]
    options: dict[str, bool]
    timezone: str | None = None
    inventory_search: InventorySearch | None = None


@dataclass
class ItemResult:
    id: str
    kind: str
    title: str
    location: str
    start: datetime
    end: datetime
    original_start: datetime
    status: str
    reason: str
    slack_minutes: int | None
    changed: bool
    cause_path: tuple[str, ...]
    violations: list[str] = field(default_factory=list)


@dataclass
class Validation:
    plan_id: str
    title: str
    summary: str
    cost_delta_inr: int
    valid: bool
    score: float
    changes_count: int
    arrival_delay_minutes: int
    items: dict[str, ItemResult]
    violations: list[str]
    assumptions: list[str]


def load_scenario(path: str | Path) -> Scenario:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items: dict[str, Item] = {}
    for row in raw["items"]:
        default_zone = row.get("timezone") or raw.get("timezone")
        start_zone = row.get("start_timezone") or default_zone
        end_zone = row.get("end_timezone") or default_zone
        item = Item(
            id=row["id"], kind=row["kind"], title=row["title"],
            start=parse_time(row["start"], start_zone), end=parse_time(row["end"], end_zone),
            location=row["location"], movable=bool(row["movable"]),
            latest_start=parse_time(row.get("latest_start"), start_zone),
            earliest_start=parse_time(row.get("earliest_start"), start_zone),
            latest_end=parse_time(row.get("latest_end"), end_zone),
        )
        if item.duration <= timedelta(0):
            raise ValueError(f"Non-positive duration: {item.id}")
        if item.earliest_start and item.latest_start and _utc(item.earliest_start) > _utc(item.latest_start):
            raise ValueError(f"Invalid start window: {item.id}")
        if item.id in items:
            raise ValueError(f"Duplicate item: {item.id}")
        items[item.id] = item
    deps = tuple(Dependency(**row) for row in raw["dependencies"])
    plans = tuple(Plan(**row) for row in raw["plans"])
    search = None
    if raw.get("inventory_search"):
        query = raw["inventory_search"]
        search = InventorySearch(
            origin_iata=str(query["origin_iata"]).upper(), destination_iata=str(query["destination_iata"]).upper(),
            departure_date=date.fromisoformat(query["departure_date"]),
            hotel_latitude=float(query["hotel_latitude"]), hotel_longitude=float(query["hotel_longitude"]),
            hotel_check_in=date.fromisoformat(query["hotel_check_in"]), hotel_check_out=date.fromisoformat(query["hotel_check_out"]),
            hotel_radius_km=int(query.get("hotel_radius_km", 5)),
        )
        if not re.fullmatch(r"[A-Z]{3}", search.origin_iata) or not re.fullmatch(r"[A-Z]{3}", search.destination_iata):
            raise ValueError("Inventory route requires three-letter IATA codes")
        if not -90 <= search.hotel_latitude <= 90 or not -180 <= search.hotel_longitude <= 180 or not 1 <= search.hotel_radius_km <= 100:
            raise ValueError("Invalid hotel search location")
        if search.hotel_check_out <= search.hotel_check_in:
            raise ValueError("Hotel checkout must follow check-in")
    scenario = Scenario(
        id=raw["id"], title=raw["title"], source=raw["source"], items=items,
        dependencies=deps, disruption_item=raw["disruption"]["item_id"],
        default_delay_minutes=raw["disruption"]["delay_minutes"],
        plans=plans, options=dict(raw["options"]), timezone=raw.get("timezone"), inventory_search=search,
    )
    topological_order(scenario)
    if scenario.disruption_item not in scenario.items:
        raise ValueError("Disruption item missing")
    return scenario


def topological_order(scenario: Scenario) -> list[str]:
    incoming = {key: 0 for key in scenario.items}
    outgoing: dict[str, list[str]] = {key: [] for key in scenario.items}
    for dep in scenario.dependencies:
        if dep.source not in incoming or dep.target not in incoming:
            raise ValueError(f"Unknown dependency endpoint: {dep}")
        if dep.min_gap_minutes < 0:
            raise ValueError("Negative dependency buffer")
        if dep.max_gap_minutes is not None and dep.max_gap_minutes < dep.min_gap_minutes:
            raise ValueError("Maximum dependency gap is shorter than minimum buffer")
        incoming[dep.target] += 1
        outgoing[dep.source].append(dep.target)
    queue = [key for key, degree in incoming.items() if degree == 0]
    result: list[str] = []
    while queue:
        current = queue.pop(0)
        result.append(current)
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if len(result) != len(scenario.items):
        raise ValueError("Dependency cycle detected")
    return result


def _apply_changes(item: Item, changes: dict[str, str]) -> Item:
    values: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in {"start", "end", "earliest_start", "latest_start", "latest_end"}:
            raise ValueError(f"Unsupported change: {key}")
        original = item.end if key in {"end", "latest_end"} else item.start
        zone_name = original.tzinfo.key if isinstance(original.tzinfo, ZoneInfo) else None
        values[key] = parse_time(value, zone_name)
    changed = replace(item, **values)
    if changed.duration <= timedelta(0):
        raise ValueError(f"Non-positive duration after change: {item.id}")
    if changed.earliest_start and changed.latest_start and _utc(changed.earliest_start) > _utc(changed.latest_start):
        raise ValueError(f"Invalid start window after change: {item.id}")
    return changed


def evaluate(
    scenario: Scenario,
    delay_minutes: int = 0,
    plan: Plan | None = None,
    unavailable_options: set[str] | None = None,
) -> Validation:
    if delay_minutes < 0 or delay_minutes > 1440:
        raise ValueError("Delay must be between 0 and 1440 minutes")
    unavailable_options = unavailable_options or set()
    working = dict(scenario.items)
    affected = working[scenario.disruption_item]
    shift = timedelta(minutes=delay_minutes)
    working[affected.id] = replace(affected, start=_add_elapsed(affected.start, shift), end=_add_elapsed(affected.end, shift))
    if plan:
        for item_id, changes in plan.changes.items():
            if item_id not in working:
                raise ValueError(f"Plan refers to unknown item: {item_id}")
            working[item_id] = _apply_changes(working[item_id], changes)
    incoming: dict[str, list[Dependency]] = {key: [] for key in working}
    for dep in scenario.dependencies:
        incoming[dep.target].append(dep)
    results: dict[str, ItemResult] = {}
    violations: list[str] = []
    for item_id in topological_order(scenario):
        item = working[item_id]
        original = scenario.items[item_id]
        predecessors = incoming[item_id]
        earliest = item.start
        if item.earliest_start and _utc(item.earliest_start) > _utc(earliest):
            earliest = item.earliest_start
        earliest_dependency: datetime | None = None
        blocking_dep: Dependency | None = None
        for dep in predecessors:
            required = _add_elapsed(results[dep.source].end, timedelta(minutes=dep.min_gap_minutes))
            if earliest_dependency is None or _utc(required) > _utc(earliest_dependency):
                earliest_dependency = required
                blocking_dep = dep
            if _utc(required) > _utc(earliest):
                earliest = required
        start = earliest.astimezone(item.start.tzinfo) if item.movable else item.start
        end = _add_elapsed(start, item.duration).astimezone(item.end.tzinfo)
        own_errors: list[str] = []
        if not item.movable and earliest_dependency and _utc(earliest_dependency) > _utc(start):
            minutes = _minutes_between(earliest_dependency, start)
            own_errors.append(f"{item.title} starts {minutes} min before the required arrival/buffer")
        if item.earliest_start and _utc(start) < _utc(item.earliest_start):
            minutes = _minutes_between(item.earliest_start, start)
            own_errors.append(f"{item.title} starts {minutes} min before its earliest allowed start")
        if item.latest_start and _utc(start) > _utc(item.latest_start):
            minutes = _minutes_between(start, item.latest_start)
            own_errors.append(f"{item.title} misses its latest start by {minutes} min")
        if item.latest_end and _utc(end) > _utc(item.latest_end):
            minutes = _minutes_between(end, item.latest_end)
            own_errors.append(f"{item.title} finishes {minutes} min after its latest allowed end")
        gap_slacks = []
        max_gap_cause: Dependency | None = None
        for dep in predecessors:
            gap = _minutes_between(start, results[dep.source].end)
            gap_slacks.append(gap - dep.min_gap_minutes)
            if dep.max_gap_minutes is not None:
                gap_slacks.append(dep.max_gap_minutes - gap)
                if gap > dep.max_gap_minutes:
                    own_errors.append(f"{item.title} starts {gap - dep.max_gap_minutes} min after the maximum connection window from {results[dep.source].title}")
                    max_gap_cause = dep
        deadline_slack = []
        if item.latest_start:
            deadline_slack.append(_minutes_between(item.latest_start, start))
        if item.latest_end:
            deadline_slack.append(_minutes_between(item.latest_end, end))
        slack = min(gap_slacks + deadline_slack) if gap_slacks or deadline_slack else None
        upstream_broken = any(results[dep.source].status == "broken" for dep in predecessors)
        dependency_forced = bool(blocking_dep and earliest_dependency and _utc(earliest_dependency) >= _utc(earliest) and _utc(earliest_dependency) > _utc(item.start))
        cause_dep = max_gap_cause or (blocking_dep if dependency_forced else None) or next((dep for dep in predecessors if results[dep.source].status == "broken"), None)
        cause_path = results[cause_dep.source].cause_path + (item.title,) if cause_dep else (item.title,)
        status = "broken" if own_errors else "at risk" if upstream_broken or (slack is not None and slack <= 15) else "unaffected"
        disrupted_item_not_replaced = item_id == scenario.disruption_item and delay_minutes and (plan is None or item_id not in plan.changes)
        if disrupted_item_not_replaced:
            status = "at risk"
        if own_errors:
            reason = "; ".join(own_errors)
        elif disrupted_item_not_replaced:
            reason = f"Arrival delayed by {delay_minutes} min; downstream rules recalculated"
        elif upstream_broken:
            reason = "Depends on a broken preceding commitment"
        elif dependency_forced:
            reason = f"Shifted by dependency: {blocking_dep.reason}"
        elif item.earliest_start and _utc(start) > _utc(item.start):
            reason = "Shifted to earliest allowed start"
        elif slack is not None and slack <= 15:
            reason = f"Only {slack} min spare buffer remains"
        else:
            reason = "All known constraints satisfied"
        row = ItemResult(
            id=item_id, kind=item.kind, title=item.title, location=item.location,
            start=start, end=end, original_start=original.start, status=status,
            reason=reason, slack_minutes=slack,
            changed=not _same_instant(start, original.start) or not _same_instant(end, original.end) or not _same_instant(item.earliest_start, original.earliest_start) or not _same_instant(item.latest_start, original.latest_start) or not _same_instant(item.latest_end, original.latest_end),
            cause_path=cause_path,
            violations=own_errors,
        )
        results[item_id] = row
        violations.extend(own_errors)
    if plan and plan.requires_option and (not scenario.options.get(plan.requires_option, False) or plan.requires_option in unavailable_options):
        violations.append(f"Required option {plan.requires_option} is unavailable")
    flight_delay = _minutes_between(results[scenario.disruption_item].end, scenario.items[scenario.disruption_item].end)
    changes_count = len(plan.changes) if plan else 0
    cost = plan.cost_delta_inr if plan else 0
    score = round(cost / 1000 + max(flight_delay, 0) / 30 + changes_count, 2)
    return Validation(
        plan_id=plan.id if plan else "impact", title=plan.title if plan else "Disruption impact",
        summary=plan.summary if plan else "Current journey after disruption",
        cost_delta_inr=cost, valid=not violations, score=score,
        changes_count=changes_count, arrival_delay_minutes=flight_delay,
        items=results, violations=violations,
        assumptions=[scenario.source, "Option availability is a simulated snapshot"],
    )


def evaluate_all(scenario: Scenario, delay_minutes: int, unavailable_options: set[str] | None = None) -> list[Validation]:
    results = [evaluate(scenario, delay_minutes, plan, unavailable_options) for plan in scenario.plans]
    return sorted(results, key=lambda row: (not row.valid, row.score, row.cost_delta_inr))
