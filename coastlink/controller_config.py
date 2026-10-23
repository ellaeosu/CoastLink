"""The Controllers screen's view of controllers.ini (the file the running game reads again within a second).

Players 1-8 ([players] playerN = auto | none | <device GUID>), each device's bindings and stick / rumble settings
([device <GUID>]: map.<CONTROL>, deadzone, outer_zone, trigger_threshold, rumble, rumble_strength, layout), the keyboard
([keyboard]) and saved profiles (config/coastlink_pad_profiles.json: copies of a device section by name). Other sections and
comments are kept as they are (settings._edit_ini). GPL-3.0-or-later.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import settings

GUID = re.compile(r"[0-9a-f]{32}")
DEVICE_KEYS = {"deadzone": (0, 0.95), "outer_zone": (0.05, 1), "trigger_threshold": (0, 1), "rumble_strength": (0, 2)}
PROFILES = "coastlink_pad_profiles.json"


def path(build: Path) -> Path:
    return Path(build) / "config" / "controllers.ini"


@settings.synchronized
def load(build: Path) -> dict:
    sections = settings._sections(settings._read(path(build)))
    players = {str(n): sections.get("players", {}).get(f"player{n}", "auto") for n in range(1, 9)}
    devices = {name[len("device "):].strip(): values for name, values in sections.items() if name.startswith("device ")}
    general = {key: value for key, value in settings.CONTROLLER_DEFAULTS.items() if key != "keyboard_player"}
    general.update(sections.get("general", {}))
    types = {name[len("type "):].strip(): values for name, values in sections.items() if name.startswith("type ")}
    return {"general": general, "types": types, "players": players, "devices": devices,
            "keyboard": sections.get("keyboard", {}), "controls": list(settings.CONTROLS)}


def _value(key: str, value) -> str | None:
    if value is None:
        return None
    if key.startswith("map."):
        control = key[4:].upper()
        if control not in settings.CONTROLS:
            raise settings.SettingsError("Unknown control: " + control)
        result = settings._pad_binding(value, control)
        return None if result == "default" else result
    if key.startswith(("axis.", "invert.")):
        if key.partition(".")[2] not in ("lx", "ly", "rx", "ry"):
            raise settings.SettingsError("Unknown stick axis: " + key)
        if key.startswith("invert."):
            return settings._choice(value, ("on", "off"), key)
        result = settings._pad_binding(value, key)
        if "," in result:
            raise settings.SettingsError("A stick axis takes one input source.")
        return None if result == "default" else result
    if key in DEVICE_KEYS:
        low, high = DEVICE_KEYS[key]
        return settings._number(value, low, high, key)
    if key == "rumble":
        return settings._choice(value, ("on", "off"), key)
    if key == "layout":
        return settings._choice(value, ("auto", "positional", "labels"), key)
    raise settings.SettingsError("Unknown controller setting: " + key)


@settings.synchronized
def save(build: Path, payload: dict) -> dict:
    """payload: {"players": {"1": "<guid>|auto|none"}, "devices": {"<guid>": {"map.A": "east", "deadzone": "0.1", "map.B": null}}}"""
    if not isinstance(payload, dict) or set(payload) - {"players", "devices"}:
        raise settings.SettingsError("Choose player assignments or controller settings.")
    if any(not isinstance(payload.get(group, {}), dict) for group in ("players", "devices")):
        raise settings.SettingsError("Controller settings must be grouped by player or device.")
    changes: dict[str, dict[str, str | None]] = {}
    for n, value in (payload.get("players") or {}).items():
        if str(n) not in {str(i) for i in range(1, 9)}:
            raise settings.SettingsError("Players are 1 to 8.")
        value = str(value).strip().lower()
        if value not in ("auto", "none") and not GUID.fullmatch(value):
            raise settings.SettingsError("Choose a connected controller for player " + str(n) + ".")
        changes.setdefault("players", {})[f"player{n}"] = value
    for guid, values in (payload.get("devices") or {}).items():
        guid = str(guid).lower()
        if not GUID.fullmatch(guid):
            raise settings.SettingsError("Unknown controller.")
        if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
            raise settings.SettingsError("Choose controller bindings or stick settings.")
        changes["device " + guid] = {key.lower() if not key.lower().startswith("map.") else "map." + key[4:].upper(): _value(key.lower(), v)
                                     for key, v in values.items()}
    target = path(build)
    updated = settings._edit_ini(settings._read(target), changes)
    prospective = settings._sections(updated)
    for section in changes:
        if section.startswith("device "):
            merged = dict(settings.CONTROLLER_DEFAULTS, **prospective.get("general", {}))
            merged.update(prospective.get(section, {}))
            if float(merged["deadzone"]) >= float(merged["outer_zone"]):
                raise settings.SettingsError("Stick dead zone must be smaller than the outer zone.")
    if updated != settings._read(target):
        settings._replace_files({target: updated})
    return load(build)


@settings.synchronized
def profiles(build: Path, args: dict) -> dict:
    file = Path(build) / "config" / PROFILES
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    action, name = args.get("action", "list"), str(args.get("name", "")).strip()
    if action not in ("list", "save", "load", "delete"):
        raise settings.SettingsError("Choose a profile action.")
    if action in ("save", "load", "delete") and not re.fullmatch(r"[\w .-]{1,40}", name):
        raise settings.SettingsError("Profile names are 1-40 letters, numbers, spaces, dots or dashes.")
    if action == "save":
        guid = str(args.get("guid", "")).lower()
        if not GUID.fullmatch(guid):
            raise settings.SettingsError("Choose a controller before saving its profile.")
        device = load(build)["devices"].get(guid, {})
        data[name] = {k: v for k, v in device.items() if _profile_key(k)}
    elif action == "delete":
        data.pop(name, None)
    elif action == "load":
        if name not in data:
            raise settings.SettingsError("No profile named " + name + ".")
        profile = data[name]
        if not isinstance(profile, dict) or any(not _profile_key(key) for key in profile):
            raise settings.SettingsError("This controller profile is not valid.")
        guid = str(args.get("guid", "")).lower()
        if not GUID.fullmatch(guid):
            raise settings.SettingsError("Choose a controller before loading its profile.")
        # Loading a profile replaces the previous profile, including clearing bindings absent from a default profile.
        previous = load(build)["devices"].get(guid, {})
        values = {key: None for key in previous if _profile_key(key)}
        values.update(profile)
        save(build, {"devices": {guid: values}})
    if action in ("save", "delete"):
        settings._replace_files({file: json.dumps(data, indent=2) + "\n"})
    return {"profiles": sorted(data)}


def _profile_key(key) -> bool:
    return isinstance(key, str) and (key.startswith(("map.", "axis.", "invert.")) or key in DEVICE_KEYS or key in ("rumble", "layout"))
