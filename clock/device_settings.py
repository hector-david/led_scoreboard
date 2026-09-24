"""Which panel the clock tools talk to, read from `settings.json`.

`settings.json` sits next to this file and is the one place a panel is named:

    {"device": "clock",
     "devices": {"clock": {"name": "LED_BLE_CD9B89CA", "address": "...", "note": "..."}}}

Swap the `device` key to point the clock at a different panel; nothing else
changes. Only `name` is used to connect -- every script in this repo finds the
panel by scanning for its advertised name rather than by address, because the
address is a stable identifier on exactly one machine and the name is not.
`address` and `note` are there so a second panel is recognisable next year.

Resolution order, highest first:

    --name on the command line     one run, one panel, no file edited
    LED_BLE_NAME                   a name, for a scheduled task or a shell
    LED_BLE_DEVICE                 an entry key from `devices`
    "device" in settings.json      the everyday setting
    ipixel.LED_NAME                only if settings.json is missing entirely

A missing file falls back rather than failing: the tools worked before this file
existed and should keep working if it is deleted. A file that *is* there but
cannot be read as written raises instead, because the alternative is connecting
to some other panel -- or to none -- and blaming the radio for a typo.

This module deliberately carries nothing but the device identity. Panel geometry
is compiled into the faces (32x16 everywhere), so pointing `device` at a panel of
another size would set its clock and draw the wrong shape; that is a code change,
not a settings change.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# Same shim as ipixel_clock.py: the transport lives with the GIF tools, and the
# repo is flat scripts rather than a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gif"))

from ipixel import LED_NAME  # noqa: E402  (the path shim has to come first)

__all__ = [
    "Device",
    "SETTINGS_FILE",
    "SettingsError",
    "device",
    "device_name",
    "devices",
    "load",
]

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

ENV_NAME = "LED_BLE_NAME"
ENV_DEVICE = "LED_BLE_DEVICE"


class SettingsError(Exception):
    """settings.json is there but cannot be used as written."""


@dataclass(frozen=True)
class Device:
    key: str
    name: str
    address: Optional[str] = None
    note: str = ""

    def summary(self) -> str:
        where = f" at {self.address}" if self.address else ""
        why = f" -- {self.note}" if self.note else ""
        return f"{self.key}: {self.name}{where}{why}"


# What the tools used before this file existed, and what they fall back to if it
# is removed. Not a duplicate of the JSON: the JSON is editable, this is not.
BUILT_IN = Device(key="built-in", name=LED_NAME, note="compiled-in default; no settings.json found")


def load(path: Optional[Path] = None) -> dict:
    """The raw file, or `{}` if there isn't one."""
    path = Path(path) if path else SETTINGS_FILE
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(
            f"{path} is not valid JSON: {exc}. A trailing comma or a missing quote is the "
            "usual cause, and JSON has no comments -- notes go in a \"note\" field."
        ) from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} should hold a JSON object, not a {type(data).__name__}")
    return data


def _devices(data: dict) -> Dict[str, Device]:
    raw = data.get("devices", {})
    if not isinstance(raw, dict):
        raise SettingsError('"devices" should be an object mapping a key to a panel')
    found: Dict[str, Device] = {}
    for key, entry in raw.items():
        if key.startswith("_"):  # _readme and friends are for the reader
            continue
        if isinstance(entry, str):  # "clock": "LED_BLE_..." is allowed shorthand
            entry = {"name": entry}
        if not isinstance(entry, dict):
            raise SettingsError(f'device "{key}" should be an object, or just the BLE name')
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SettingsError(
                f'device "{key}" has no "name". That is the BLE advertised name, the one '
                'a scan shows -- for example "LED_BLE_CD9B89CA".'
            )
        address = entry.get("address") or None
        found[key] = Device(
            key=key, name=name.strip(), address=address, note=str(entry.get("note", ""))
        )
    return found


def devices(path: Optional[Path] = None) -> Dict[str, Device]:
    """Every panel the file knows about, keyed the way the file keys them."""
    return _devices(load(path))


def device(key: Optional[str] = None, *, path: Optional[Path] = None) -> Device:
    """The selected panel: `key`, else $LED_BLE_DEVICE, else the file's "device"."""
    data = load(path)
    known = _devices(data)
    if not known:
        return BUILT_IN

    wanted = key or os.environ.get(ENV_DEVICE) or data.get("device")
    if wanted is None or (isinstance(wanted, str) and not wanted.strip()):
        if len(known) == 1:
            return next(iter(known.values()))
        raise SettingsError(
            f'{SETTINGS_FILE.name} lists {", ".join(sorted(known))} but does not say which '
            'one to use. Add a top-level "device": "<key>".'
        )
    wanted = str(wanted).strip()
    if wanted not in known:
        raise SettingsError(
            f'device "{wanted}" is not in {SETTINGS_FILE.name}. It knows: '
            f'{", ".join(sorted(known))}.'
        )
    return known[wanted]


def device_name(
    override: Optional[str] = None, *, key: Optional[str] = None, path: Optional[Path] = None
) -> str:
    """The BLE name to scan for, after every override has had its say."""
    if override and override.strip():
        return override.strip()
    env = os.environ.get(ENV_NAME)
    if env and env.strip():
        return env.strip()
    return device(key, path=path).name


def describe(override: Optional[str] = None, *, key: Optional[str] = None) -> str:
    """One line for the tools to print, so a wrong panel is visible before the scan."""
    name = device_name(override, key=key)
    if override and override.strip():
        return f"Panel: {name} (--name)"
    if not override and os.environ.get(ENV_NAME, "").strip():
        return f"Panel: {name} (${ENV_NAME})"
    chosen = device(key)
    if chosen is BUILT_IN:
        return f"Panel: {name} (built-in default; no {SETTINGS_FILE.name})"
    source = f"${ENV_DEVICE}" if (not key and os.environ.get(ENV_DEVICE)) else SETTINGS_FILE.name
    return f"Panel: {name} ({chosen.key}, from {source})"


def main(argv=None) -> int:
    """`py device_settings.py` -- what the file resolves to, and what else is in it."""
    try:
        print(describe())
        known = devices()
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if known:
        print(f"\n{SETTINGS_FILE} knows:")
        for entry in known.values():
            print(f"  {entry.summary()}")
        print('\nEdit "device" in that file to switch panels.')
    else:
        print(f"\n{SETTINGS_FILE} does not exist; using the compiled-in name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
