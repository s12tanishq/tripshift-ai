"""Model-driven TripShift agent with local, validated travel tools."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI, RateLimitError

from .core import Scenario, Validation, evaluate, evaluate_all
from .inventory import InventorySnapshot, assess_flight_offers

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-3.5-flash-lite"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
}


def schema(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


TOOL_SCHEMAS = [
    schema("read_itinerary", "Read the simulated journey, original times, hotel deadline, and dependency rules."),
    schema("read_provider_inventory", "Read a separately searched India-localized flight and hotel search snapshot, including source time, indicative INR prices, and unknown states. These results are not mapped to simulated plan IDs."),
    schema("validate_provider_flights", "Check returned provider flight times against the journey dependency rules. This only checks timing; it does not confirm a fare, seat, or rebooking cost."),
    schema("set_flight_delay", "Record the user's flight arrival delay in whole minutes. Call this before impact analysis.", {"delay_minutes": {"type": "integer", "minimum": 0, "maximum": 1440}}, ["delay_minutes"]),
    schema("analyze_dependencies", "Calculate the delay's ripple through the journey, including broken commitments and causal paths."),
    schema("search_recovery_options", "Inspect available scenario recovery actions and their required options."),
    schema("validate_recovery_options", "Run deterministic checks on every recovery candidate and return valid/blocked results."),
    schema("select_recovery", "Choose one previously validated, valid plan by exact plan ID. Never select a blocked plan.", {"plan_id": {"type": "string"}, "reason": {"type": "string", "description": "A short explanation of the trade-off, grounded in validation results."}}, ["plan_id", "reason"]),
    schema("select_fallback", "Choose a different, previously validated valid plan as the fallback if the selected option becomes unavailable.", {"plan_id": {"type": "string"}}, ["plan_id"]),
    schema("report_no_feasible_plan", "Use only after validation proves every recovery candidate is blocked."),
    schema("prepare_messages", "Prepare review-only driver, hotel, and meeting drafts for the selected plan, or a blocker note if none is feasible."),
]

SYSTEM_PROMPT = """You are TripShift, an AI travel disruption agent for a simulated competition journey.
Use the supplied tools to inspect the itinerary, record the flight delay, calculate dependency impact, inspect alternatives, validate every candidate, select a recovery, select a distinct checked fallback when possible, and prepare communication drafts. If provider evidence is supplied, read it and validate returned flight timings. Decide which tools to call based on their results. A final answer is allowed only after these steps are complete.
The deterministic validator is authoritative. Never calculate journey feasibility yourself, select an unvalidated plan, invent availability, claim a booking is confirmed, or say a message was sent. If all plans are blocked, call report_no_feasible_plan and explain the blockers. Simulated plan IDs are not linked to provider offers. Travel search data, when supplied, is separate indicative evidence and may be cached or change. Some flight schedules fit only if airport pickup is moved; that driver change requires confirmation. A hotel search does not verify late check-in at the existing booking. If the user's request is not a numeric or derivable flight delay, state that this version cannot handle it rather than guessing. Keep the final response concise and grounded in tool results."""


@dataclass(frozen=True)
class TraceEvent:
    step: int
    tool: str
    detail: str


@dataclass
class AgentRun:
    delay_minutes: int
    impact: Validation
    plans: list[Validation]
    selected: Validation | None
    fallback: Validation | None
    messages: list[dict[str, str]]
    trace: list[TraceEvent]
    provider: str
    model: str
    summary: str
    selection_reason: str = ""


class AgentWorkflowError(RuntimeError):
    pass


def draft_messages(impact: Validation, selected: Validation | None) -> list[dict[str, str]]:
    if selected is None:
        return [{"recipient": "Traveller", "subject": "Journey needs a decision", "body": "No checked recovery plan is available from the current scenario options. Review the listed blockers and contact the airline, hotel, or meeting organiser directly.", "status": "Draft only"}]
    rows: list[dict[str, str]] = []
    transfer = selected.items.get("transfer")
    hotel = selected.items.get("hotel")
    meeting = selected.items.get("meeting")
    if transfer and transfer.changed:
        rows.append({"recipient": "Driver", "subject": "Updated airport pickup", "body": f"Please plan the pickup for {transfer.start:%d %b %H:%M %Z}. This is a proposed schedule pending confirmation.", "status": "Draft only"})
    if hotel and (hotel.changed or impact.items.get("hotel", hotel).status == "broken"):
        rows.append({"recipient": "Hotel", "subject": "Updated check-in arrival", "body": f"Our proposed arrival is {hotel.start:%d %b %H:%M %Z}. Please confirm that check-in will be possible at that time.", "status": "Draft only"})
    if meeting and (meeting.changed or impact.items.get("meeting", meeting).status == "broken"):
        body = f"We propose a meeting start of {meeting.start:%d %b %H:%M %Z}. Please confirm this still works for you." if meeting.changed else f"Our checked recovery still targets the original {meeting.start:%d %b %H:%M %Z} meeting. We will confirm the travel arrangement before treating attendance as final."
        rows.append({"recipient": "Meeting attendees", "subject": "Travel update and meeting time", "body": body, "status": "Draft only"})
    return rows


@dataclass
class AgentSession:
    scenario: Scenario
    unavailable_options: set[str]
    provider: str
    model: str
    inventory: InventorySnapshot | None = None
    delay_minutes: int | None = None
    impact: Validation | None = None
    plans: list[Validation] | None = None
    selected: Validation | None = None
    fallback: Validation | None = None
    no_feasible_plan: bool = False
    messages: list[dict[str, str]] | None = None
    selection_reason: str = ""
    trace: list[TraceEvent] = field(default_factory=list)
    itinerary_read: bool = False
    options_searched: bool = False
    inventory_read: bool = False
    provider_flights_validated: bool = False

    def log(self, tool: str, detail: str) -> None:
        self.trace.append(TraceEvent(len(self.trace) + 1, tool, detail[:500]))

    def missing_steps(self) -> list[str]:
        missing = []
        if not self.itinerary_read:
            missing.append("read the itinerary")
        if self.inventory is not None and not self.inventory_read:
            missing.append("read provider evidence")
        if self.inventory is not None and self.inventory.flights.offers and not self.provider_flights_validated:
            missing.append("validate provider flight timings")
        if self.delay_minutes is None:
            missing.append("record the delay")
        if self.impact is None:
            missing.append("analyze dependencies")
        if not self.options_searched:
            missing.append("search recovery options")
        if self.plans is None:
            missing.append("validate recovery options")
        elif any(plan.valid for plan in self.plans):
            if self.selected is None:
                missing.append("select a validated recovery")
            elif self.selected.plan_id != "no_change" and sum(plan.valid for plan in self.plans) > 1 and self.fallback is None:
                missing.append("select a validated fallback")
        elif not self.no_feasible_plan:
            missing.append("report that no plan is feasible")
        if self.messages is None:
            missing.append("prepare messages")
        return missing

    def _plan(self, plan_id: str) -> Validation | None:
        return next((row for row in self.plans or [] if row.plan_id == plan_id), None)

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._call(name, args)
            self.log(name, result.get("brief", "Completed"))
            return result
        except (ValueError, TypeError) as exc:
            self.log(name, f"Rejected: {exc}")
            return {"error": str(exc)}

    def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "read_itinerary":
            self.itinerary_read = True
            return {
                "scenario": self.scenario.title, "source": self.scenario.source, "timezone": self.scenario.timezone,
                "items": [{"id": item.id, "kind": item.kind, "title": item.title, "start": item.start.isoformat(), "end": item.end.isoformat(), "earliest_start": item.earliest_start.isoformat() if item.earliest_start else None, "latest_start": item.latest_start.isoformat() if item.latest_start else None, "latest_end": item.latest_end.isoformat() if item.latest_end else None, "movable": item.movable} for item in self.scenario.items.values()],
                "dependencies": [{"source": dep.source, "target": dep.target, "min_gap_minutes": dep.min_gap_minutes, "max_gap_minutes": dep.max_gap_minutes, "reason": dep.reason} for dep in self.scenario.dependencies],
                "brief": f"Read {len(self.scenario.items)} commitments and {len(self.scenario.dependencies)} dependency rules",
            }
        if name == "read_provider_inventory":
            self.inventory_read = True
            if self.inventory is None:
                return {"state": "unknown", "brief": "No provider search snapshot supplied"}
            result = self.inventory.for_agent()
            result["brief"] = f"Read provider evidence: flights {self.inventory.flights.state}; hotels {self.inventory.hotels.state}"
            return result
        if name == "validate_provider_flights":
            if self.inventory is None or not self.inventory_read:
                raise ValueError("Read provider evidence first")
            if self.delay_minutes is None:
                raise ValueError("Record the flight delay first")
            checks = assess_flight_offers(self.scenario, self.delay_minutes, self.inventory.flights)
            self.provider_flights_validated = True
            rows = [{"offer_id": row.offer.id, "timing_valid": row.validation.valid if row.validation else False, "violations": row.validation.violations if row.validation else [row.issue], "arrival_delay_minutes": row.validation.arrival_delay_minutes if row.validation else None, "expires_at": row.offer.expires_at.isoformat() if row.offer.expires_at else None, "condition": row.condition} for row in checks]
            return {"checks": rows, "brief": f"Checked timing for {len(rows)} provider flight offer(s)"}
        if name == "set_flight_delay":
            delay = args.get("delay_minutes")
            if type(delay) is not int or not 0 <= delay <= 1440:
                raise ValueError("delay_minutes must be an integer from 0 to 1440")
            self.delay_minutes = delay
            self.impact = None
            self.plans = None
            self.selected = None
            self.fallback = None
            self.no_feasible_plan = False
            self.messages = None
            self.provider_flights_validated = False
            return {"delay_minutes": delay, "brief": f"Recorded {delay} minute flight delay"}
        if name == "analyze_dependencies":
            if self.delay_minutes is None:
                raise ValueError("Record the flight delay first")
            self.impact = evaluate(self.scenario, self.delay_minutes)
            rows = [{"id": item.id, "status": item.status, "start": item.start.isoformat(), "reason": item.reason, "slack_minutes": item.slack_minutes, "cause_path": item.cause_path} for item in self.impact.items.values()]
            broken = [row["id"] for row in rows if row["status"] == "broken"]
            return {"items": rows, "violations": self.impact.violations, "brief": f"Found {len(broken)} broken commitment(s): {', '.join(broken) if broken else 'none'}"}
        if name == "search_recovery_options":
            if self.delay_minutes is None:
                raise ValueError("Record the flight delay first")
            self.options_searched = True
            rows = [{"plan_id": plan.id, "title": plan.title, "summary": plan.summary, "cost_delta_inr": plan.cost_delta_inr, "explicit_edits": len(plan.changes), "option_available": not plan.requires_option or (self.scenario.options.get(plan.requires_option, False) and plan.requires_option not in self.unavailable_options)} for plan in self.scenario.plans]
            return {"options": rows, "brief": f"Inspected {len(rows)} simulated recovery options"}
        if name == "validate_recovery_options":
            if self.delay_minutes is None:
                raise ValueError("Record the flight delay first")
            self.plans = evaluate_all(self.scenario, self.delay_minutes, self.unavailable_options)
            rows = [{"plan_id": plan.plan_id, "title": plan.title, "valid": plan.valid, "score": plan.score, "cost_delta_inr": plan.cost_delta_inr, "arrival_delay_minutes": plan.arrival_delay_minutes, "explicit_edits": plan.changes_count, "violations": plan.violations, "assumptions": plan.assumptions} for plan in self.plans]
            valid = sum(row["valid"] for row in rows)
            return {"plans": rows, "brief": f"Validated {len(rows)} plans; {valid} passed hard checks"}
        if name == "select_recovery":
            if self.plans is None:
                raise ValueError("Validate recovery options first")
            plan = self._plan(args.get("plan_id", ""))
            if plan is None or not plan.valid:
                raise ValueError("Plan ID is unknown or failed validation")
            self.selected = plan
            self.fallback = None
            self.no_feasible_plan = False
            self.messages = None
            self.selection_reason = str(args.get("reason", ""))[:300]
            return {"selected": plan.plan_id, "validated": True, "brief": f"Selected validated plan: {plan.title}"}
        if name == "select_fallback":
            if self.selected is None:
                raise ValueError("Select the primary recovery first")
            plan = self._plan(args.get("plan_id", ""))
            if plan is None or not plan.valid or plan.plan_id == self.selected.plan_id:
                raise ValueError("Fallback must be a different validated, valid plan")
            self.fallback = plan
            return {"fallback": plan.plan_id, "validated": True, "brief": f"Prepared fallback: {plan.title}"}
        if name == "report_no_feasible_plan":
            if self.plans is None:
                raise ValueError("Validate recovery options first")
            if any(plan.valid for plan in self.plans):
                raise ValueError("At least one validated plan is feasible")
            self.no_feasible_plan = True
            return {"blocked": True, "violations": {plan.plan_id: plan.violations for plan in self.plans}, "brief": "All recovery candidates are blocked"}
        if name == "prepare_messages":
            if self.impact is None:
                raise ValueError("Analyze dependencies first")
            if self.selected is None and not self.no_feasible_plan:
                raise ValueError("Select a recovery or report no feasible plan first")
            self.messages = draft_messages(self.impact, self.selected)
            return {"drafts": self.messages, "brief": f"Prepared {len(self.messages)} review-only draft(s)"}
        raise ValueError(f"Unknown tool: {name}")

    def result(self, summary: str) -> AgentRun:
        if self.missing_steps():
            raise AgentWorkflowError("Agent stopped before completing: " + ", ".join(self.missing_steps()))
        assert self.delay_minutes is not None and self.impact is not None and self.plans is not None and self.messages is not None
        return AgentRun(self.delay_minutes, self.impact, self.plans, self.selected, self.fallback, self.messages, self.trace, self.provider, self.model, summary[:1500], self.selection_reason)


def _assistant_message(message: Any) -> dict[str, Any]:
    calls = []
    for call in message.tool_calls or []:
        item = {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
        extra = getattr(call, "model_extra", None) or {}
        if extra.get("extra_content"):
            item["extra_content"] = extra["extra_content"]
        calls.append(item)
    return {"role": "assistant", "content": message.content or "", "tool_calls": calls}


def _run_provider(scenario: Scenario, request: str, unavailable_options: set[str], provider: str, model: str, client: Any, max_steps: int, inventory: InventorySnapshot | None = None) -> AgentRun:
    session = AgentSession(scenario, unavailable_options, provider, model, inventory)
    session.log("provider", f"Connected to {provider} / {model}")
    prompt = SYSTEM_PROMPT + ("\nProvider evidence has been supplied. Call read_provider_inventory and, if it contains flight offers, validate_provider_flights before choosing a recovery." if inventory is not None else "")
    messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}, {"role": "user", "content": request[:2000]}]
    for _ in range(max_steps):
        response = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SCHEMAS, tool_choice="auto")
        if not response.choices:
            raise AgentWorkflowError("Provider returned no response choice")
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            missing = session.missing_steps()
            if missing:
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append({"role": "user", "content": "The workflow is incomplete. Use the available tools to: " + "; ".join(missing) + ". Do not finish early."})
                continue
            return session.result(message.content or "Recovery analysis complete.")
        messages.append(_assistant_message(message))
        for call in calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                result = {"error": f"Malformed tool arguments: {exc}"}
                session.log(call.function.name, "Rejected malformed arguments")
            else:
                result = session.call(call.function.name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
    raise AgentWorkflowError("Model did not complete the required tool workflow within the step limit")


def run_trip_agent(scenario: Scenario, request: str, unavailable_options: set[str] | None = None, provider: str = "auto", max_steps: int = 14, inventory: InventorySnapshot | None = None) -> AgentRun:
    """Run a real model tool loop. A failed provider restarts with a clean, read-only session."""
    if not request.strip():
        raise AgentWorkflowError("Describe the flight disruption before analyzing")
    if provider != "auto" and provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    names = list(PROVIDERS) if provider == "auto" else [provider]
    attempts = []
    for name in names:
        base_url, key_env, model_env, default_model = PROVIDERS[name]
        key = os.getenv(key_env)
        if not key:
            attempts.append(f"{name}: API key missing")
            continue
        model = os.getenv(model_env) or default_model
        try:
            client = OpenAI(base_url=base_url, api_key=key, timeout=25, max_retries=0)
            return _run_provider(scenario, request, unavailable_options or set(), name, model, client, max_steps, inventory)
        except RateLimitError:
            attempts.append(f"{name}: rate limit or quota reached")
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                attempts.append(f"{name}: API key was rejected")
            elif exc.status_code >= 500:
                attempts.append(f"{name}: provider temporarily unavailable (HTTP {exc.status_code})")
            else:
                attempts.append(f"{name}: provider rejected the request (HTTP {exc.status_code})")
        except AgentWorkflowError as exc:
            attempts.append(f"{name}: {exc}")
        except Exception as exc:
            attempts.append(f"{name}: {type(exc).__name__}")
    raise AgentWorkflowError("No model completed the analysis. " + " | ".join(attempts) + ". Check provider quota and .env keys, then retry.")
