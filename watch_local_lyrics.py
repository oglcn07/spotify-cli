"""Validated, atomic storage for per-track user-supplied LRC files."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


LYRICS_DIR = Path.home() / '.config/spotify-cli/lyrics'
MAX_LRC_BYTES = 1024 * 1024


def track_key(state):
    if not state or not state.get('title') or not state.get('artist'):
        raise ValueError('Önce bir şarkı çal; başlık ve sanatçı bilgisi gerekiyor.')
    return (state['title'], state['artist'], state.get('album', ''), state.get('mpris:length', 0))


def lyrics_path(key):
    title, artist, album, _ = key
    # Album separates studio/live versions; ignore rounded duration changes.
    identity = json.dumps([title, artist, album], ensure_ascii=False).encode('utf-8')
    digest = hashlib.sha256(identity).hexdigest()[:16]
    label = re.sub(r'[^\w -]', '', f'{artist} - {title}', flags=re.UNICODE).strip()[:70]
    return LYRICS_DIR / f'{label or "parca"}-{digest}.lrc'


def read_lrc(path):
    from watch_lyrics import parse_lrc

    with Path(path).open('rb') as stream:
        data = stream.read(MAX_LRC_BYTES + 1)
    if len(data) > MAX_LRC_BYTES:
        raise ValueError('LRC dosyası 1 MiB sınırını aşıyor.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('LRC dosyası UTF-8 biçiminde olmalı.') from None
    lines = parse_lrc(text)
    if not lines or not any(words for _, words in lines):
        raise ValueError('Dosyada zaman damgalı şarkı sözü bulunamadı.')
    return text, lines


def load_local(key):
    try:
        _, lines = read_lrc(lyrics_path(key))
    except FileNotFoundError:
        return None
    return lines, [], ''


def import_lrc(source, key):
    text, lines = read_lrc(source)
    destination = lyrics_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=destination.parent,
                                         encoding='utf-8', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination, len(lines)
