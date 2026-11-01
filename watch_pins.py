"""Local collection shortcuts, independent of the Spotify saved library."""

import json
import os
from pathlib import Path
import re
import tempfile

PINS_PATH = Path.home() / '.config/spotify-cli/pins.json'
COLLECTIONS = ('album', 'artist', 'playlist')


def clean_pin(item):
    uri = item.get('uri', '')
    match = re.fullmatch(r'spotify:(album|artist|playlist):([A-Za-z0-9]+)', uri) if isinstance(uri, str) else None
    if not match:
        raise ValueError('Yalnız albüm, sanatçı ve playlist sabitlenebilir.')
    name = item.get('name') or uri
    return {'uri': uri, 'type': match[1], 'name': ''.join(c for c in str(name) if c.isprintable())[:160]}


def load_pins():
    try:
        with PINS_PATH.open('rb') as stream:
            data = stream.read(256 * 1024 + 1)
        if len(data) > 256 * 1024:
            return []
        records = json.loads(data)
        if not isinstance(records, list):
            return []
    except (OSError, ValueError):
        return []
    result, seen = [], set()
    for record in records[:100]:
        try:
            item = clean_pin(record)
        except (ValueError, AttributeError, TypeError):
            continue
        if item['uri'] not in seen:
            result.append(item)
            seen.add(item['uri'])
    return result


def save_pins(items):
    PINS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=PINS_PATH.parent, encoding='utf-8', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(items[:100], stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, PINS_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def pin_item(item, remove=False, toggle=False):
    item = clean_pin(item)
    pins = load_pins()
    exists = any(pin['uri'] == item['uri'] for pin in pins)
    pins = [pin for pin in pins if pin['uri'] != item['uri']]
    added = not remove and not (toggle and exists)
    if added:
        if len(pins) >= 100:
            raise ValueError('En fazla 100 koleksiyon sabitlenebilir.')
        pins.append(item)
    save_pins(pins)
    return added
