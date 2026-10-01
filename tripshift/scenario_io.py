"""Portable demo setup files. These contain inputs only, never keys or model results."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

VERSION = 1
SCENARIO_ID = "nagpur-demo"
MODES = ("Normal", "Second shock: chosen flight unavailable", "Impossible: all options unavailable")
PROVIDERS = ("Auto", "Gemini", "Groq")
MAX_FILE_BYTES = 1_048_576


@dataclass(frozen=True)
class SavedSetup:
    name: str
    delay_minutes: int
    description: str
    mode: str
    provider: str

    def validate(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 80:
            raise ValueError("Scenario name must be 1–80 characters")
        if type(self.delay_minutes) is not int or not 0 <= self.delay_minutes <= 360 or self.delay_minutes % 15:
            raise ValueError("Delay must be a 15-minute step from 0 to 360")
        if not isinstance(self.description, str) or len(self.description) > 500:
            raise ValueError("Description must be at most 500 characters")
        if self.mode not in MODES:
            raise ValueError("Unknown scenario mode")
        if self.provider not in PROVIDERS:
            raise ValueError("Unknown model provider")


def save_setup(setup: SavedSetup) -> bytes:
    setup.validate()
    data = {
        "format": "tripshift-setup", "version": VERSION, "scenario_id": SCENARIO_ID,
        "name": setup.name.strip(), "delay_minutes": setup.delay_minutes,
        "description": setup.description, "mode": setup.mode, "provider": setup.provider,
    }
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_setup(payload: bytes) -> SavedSetup:
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("Saved scenario file is too large")
    try:
        data: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("This is not a valid TripShift JSON setup") from exc
    if not isinstance(data, dict) or data.get("format") != "tripshift-setup" or data.get("version") != VERSION:
        raise ValueError("Unsupported TripShift setup format")
    if data.get("scenario_id") != SCENARIO_ID:
        raise ValueError("This setup belongs to a different journey")
    try:
        setup = SavedSetup(data["name"], data["delay_minutes"], data["description"], data["mode"], data["provider"])
    except KeyError as exc:
        raise ValueError("Saved setup is missing a required field") from exc
    setup.validate()
    return setup
