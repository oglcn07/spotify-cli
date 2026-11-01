"""Portable OAuth configuration and private token persistence."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from spotipy.cache_handler import CacheFileHandler

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / '.config/spotify-cli'
CLIENT_CONFIG = CONFIG_DIR / 'oauth.json'
LEGACY_CLIENT = ROOT / '.spotify-client-id'
LEGACY_CACHE = ROOT / '.token-cache'
REDIRECT_URI = 'http://127.0.0.1:8888/callback'


def valid_client_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{32}', value) is not None


def legacy_client_id():
    try:
        return LEGACY_CLIENT.read_text().strip()
    except OSError:
        return ''


def client_id():
    value = os.environ.get('SPOTIFY_CLIENT_ID', '').strip()
    if not value:
        try:
            config = json.loads(CLIENT_CONFIG.read_text())
            value = config.get('client_id', '') if isinstance(config, dict) else ''
        except (OSError, ValueError):
            value = ''
    if not value:
        value = legacy_client_id()
    if not valid_client_id(value):
        raise RuntimeError('Arama ve favoriler için önce spotify configure çalıştır; kendi Web API Client ID bilgini gir.')
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_client_id(value):
    value = value.strip()
    if not valid_client_id(value):
        raise ValueError('Client ID, Spotify Dashboard üzerinde verilen 32 karakterlik kimlik olmalı.')
    atomic_json(CLIENT_CONFIG, {'client_id': value})


def token_cache_path(selected_client):
    # Keep the owner's existing session; new installs never use the project tree.
    if selected_client == legacy_client_id() and LEGACY_CACHE.is_file():
        return LEGACY_CACHE
    suffix = hashlib.sha256(selected_client.encode()).hexdigest()[:16]
    return CONFIG_DIR / f'token-{suffix}.json'


class PrivateTokenCache(CacheFileHandler):
    def save_token_to_cache(self, token_info):
        atomic_json(self.cache_path, token_info)
