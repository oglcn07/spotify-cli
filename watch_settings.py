"""Small, validated preferences file; never stores account credentials."""

import json
import os
import tempfile
from pathlib import Path


SETTINGS_PATH = Path.home() / ".config/spotify-cli/preferences.json"
WATCH_DESIGNS = ("islands", "classic")
COVER_MODES = ("8-bit", "16-bit", "Glitch", "ASCII")


def load_settings():
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    if data.get("design") in WATCH_DESIGNS:
        result["design"] = data["design"]
    if data.get("cover_mode") in COVER_MODES:
        result["cover_mode"] = data["cover_mode"]
    if type(data.get("volume")) is int and 0 <= data["volume"] <= 100:
        result["volume"] = data["volume"]
    if type(data.get("show_art")) is bool:
        result["show_art"] = data["show_art"]
    if type(data.get("show_lyrics")) is bool:
        result["show_lyrics"] = data["show_lyrics"]
    for key, low, high in (("background_brightness", 15, 85), ("panel_width", 32, 68), ("lyrics_width", 24, 64)):
        value = data.get(key)
        if type(value) is int and low <= value <= high:
            result[key] = value
    return result


def save_settings(**changes):
    data = load_settings()
    data.update(changes)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=SETTINGS_PATH.parent,
                                         delete=False, encoding="utf-8") as stream:
            path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False)
            stream.write("\n")
        os.replace(path, SETTINGS_PATH)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
