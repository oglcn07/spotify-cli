"""Optional official Musixmatch adapter. Never include credential URLs in errors."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class MusixmatchError(Exception):
    def __init__(self, status, headers=None):
        self.code = status
        self.headers = headers or {}
        messages = {401: "API anahtarı geçersiz", 402: "API kotası veya plan erişimi yetersiz",
                    403: "bu içerik için API erişimi yok", 404: "söz bulunamadı",
                    429: "istek sınırı"}
        super().__init__(f"Musixmatch: {messages.get(status, 'servis hatası')} ({status})")


def configured_key():
    return os.environ.get("MUSIXMATCH_API_KEY", "").strip()


def api_call(method, params, api_key):
    query = urllib.parse.urlencode({**params, "apikey": api_key, "format": "json"})
    request = urllib.request.Request(
        "https://api.musixmatch.com/ws/1.1/" + method + "?" + query,
        headers={"User-Agent": "spotify-cli/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            data = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise MusixmatchError(error.code, error.headers) from None
    except OSError:
        raise MusixmatchError(503) from None
    if len(data) > 1024 * 1024:
        raise MusixmatchError(502)
    try:
        message = json.loads(data)["message"]
        status = int(message["header"]["status_code"])
        if status != 200:
            raise MusixmatchError(status)
        return message.get("body") or {}
    except (ValueError, TypeError, KeyError):
        raise MusixmatchError(502) from None


def fetch_musixmatch(key, api_key):
    # Imported here to keep the LRC parser shared without an import cycle.
    from watch_lyrics import parse_lrc

    title, artist, _, duration = key
    params = {"q_track": title, "q_artist": artist}
    subtitle_params = {**params, "subtitle_format": "lrc"}
    if duration > 0:
        subtitle_params.update(f_subtitle_length=duration, f_subtitle_length_max_deviation=2)
    subtitle_error = None
    try:
        body = api_call("matcher.subtitle.get", subtitle_params, api_key)
        subtitle = body.get("subtitle") or {}
        if subtitle.get("restricted"):
            raise MusixmatchError(403)
        synced = parse_lrc(subtitle.get("subtitle_body"))
        if synced:
            return synced, [], subtitle.get("lyrics_copyright") or ""
    except MusixmatchError as error:
        if error.code not in (403, 404):
            raise
        subtitle_error = error
    body = api_call("matcher.lyrics.get", params, api_key)
    lyrics = body.get("lyrics") or {}
    if lyrics.get("restricted"):
        raise MusixmatchError(403)
    plain = (lyrics.get("lyrics_body") or "").strip().splitlines()
    if not plain:
        raise subtitle_error or MusixmatchError(404)
    return [], plain, lyrics.get("lyrics_copyright") or ""
