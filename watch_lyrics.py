"""LRCLIB lyrics loading off the curses thread, with bounded session caching."""

from bisect import bisect_right
from collections import OrderedDict
import json
import queue
import random
import re
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from watch_local_lyrics import load_local
from watch_musixmatch import configured_key, fetch_musixmatch, MusixmatchError


STAMP = re.compile(r"\[(\d+):([0-5]\d)(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    lines = []
    offset = re.search(r"\[offset:([+-]?\d+)\]", text or "", re.I)
    shift = int(offset[1]) / 1000 if offset else 0
    for line in (text or "").splitlines():
        stamps = list(STAMP.finditer(line))
        if not stamps:
            continue
        words = line[stamps[-1].end():].strip()
        for stamp in stamps:
            seconds = int(stamp[1]) * 60 + int(stamp[2])
            seconds += float("0." + stamp[3]) if stamp[3] else 0
            lines.append((seconds + shift, words))
    return sorted(lines, key=lambda line: line[0])


def active_line(lines, position):
    return bisect_right([line[0] for line in lines], position) - 1


def lyric_position(state, sampled_at, now):
    if not state:
        return 0
    position = state.get("position_precise", state.get("position", 0))
    if state.get("status") == "Playing":
        position += max(0, now - sampled_at)
    duration = state.get("mpris:length", 0)
    return max(0, min(position, duration) if duration else position)


def panel_layout(columns, height, artwork=True, focused=False):
    """Return (info width, cover left/width, lyrics left/width)."""
    if focused and height >= 12:
        return columns - 2, 0, 0, 1, max(0, columns - 2)
    if columns >= 120 and height >= 18:
        info = min(48, columns // 3)
        lyrics_width = min(64, columns // 3)
        lyrics_left = columns - lyrics_width - 1
        cover_left = info + 3
        return info, cover_left, max(0, lyrics_left - cover_left - 3) if artwork else 0, lyrics_left, lyrics_width
    if artwork and columns >= 90 and height >= 18:
        info = min(60, columns // 2)
        return info, info + 3, columns - info - 5, 0, 0
    return max(0, columns - 2), 0, 0, 0, 0


def fetch_lyrics(key):
    title, artist, album, duration = key
    params = {"track_name": title, "artist_name": artist}
    if album:
        params["album_name"] = album
    if 1 <= duration <= 3600:
        params["duration"] = duration
    request = urllib.request.Request(
        "https://lrclib.net/api/get?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "spotify-cli/1.0 (personal terminal lyrics client)",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Lyrics response too large")
    record = json.loads(data)
    synced = parse_lrc(record.get("syncedLyrics"))
    plain = (record.get("plainLyrics") or "").splitlines()
    message = "Enstrümantal parça" if record.get("instrumental") else "Söz bulunamadı"
    return synced, plain, message


def fetch_fallback_record(title, artist):
    path = "/".join(urllib.parse.quote(value, safe="") for value in (artist, title))
    request = urllib.request.Request(
        "https://api.lyrics.ovh/v1/" + path,
        headers={"User-Agent": "spotify-cli/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Lyrics response too large")
    plain = (json.loads(data).get("lyrics") or "").strip().splitlines()
    return [], plain, "" if plain else "Söz bulunamadı"


def fetch_fallback(key):
    title, artist, _, _ = key
    try:
        result = fetch_fallback_record(title, artist)
        if result[1]:
            return result
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        if ", " not in artist:
            raise
    # Multi-artist credits often have only the lead artist in lyrics catalogs.
    if ", " in artist:
        return fetch_fallback_record(title, artist.split(", ", 1)[0])
    return result


def retry_delay(error, default=30):
    value = (getattr(error, "headers", None) or {}).get("Retry-After", str(default))
    try:
        delay = max(1, float(value))
    except ValueError:
        try:
            delay = max(1, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            delay = default
    return delay + random.uniform(0, 1)


class Lyrics:
    def __init__(self):
        self.jobs = queue.Queue(maxsize=1)
        self.results = queue.Queue()
        self.stopped = threading.Event()
        self.key = None
        self.synced, self.plain = [], []
        self.message = "Çalan parça yok"
        self.offset = 0
        self.source = "LRCLIB"
        self.next_retry = float("inf")
        self.thread = threading.Thread(target=self._load, daemon=True)
        self.thread.start()

    def request(self, state, force=False):
        key = ((state.get("title", ""), state.get("artist", ""),
                state.get("album", ""), state.get("mpris:length", 0))
               if state and state.get("title") and state.get("artist") else None)
        if key == self.key and not force and time.monotonic() < self.next_retry:
            return
        changed = key != self.key
        self.key = key
        self.next_retry = float("inf")
        if changed:
            self.synced, self.plain, self.offset = [], [], 0
        if changed or not (self.synced or self.plain):
            self.message = "Sözler yükleniyor..." if key else "Çalan parça yok"
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(key)

    def _load(self):
        cache = OrderedDict()
        primary_retry = fallback_retry = next_request = musixmatch_retry = 0
        musixmatch_key = configured_key()
        musixmatch_error = ""
        primary_error = "LRCLIB beklemede"
        fallback_error = "lyrics.ovh beklemede"
        while not self.stopped.is_set():
            key = self.jobs.get()
            if self.stopped.is_set():
                return
            if key is None:
                continue
            local_error = ""
            try:
                local = load_local(key)
            except (OSError, ValueError):
                local = None
                local_error = "Yerel LRC okunamadı (UTF-8 ve zaman damgalarını kontrol et)"
            if local:
                self.results.put((key, (*local, "Yerel LRC", float("inf"))))
                continue
            if key in cache:
                expires, cached = cache[key]
                if expires > time.monotonic():
                    cache.move_to_end(key)
                    remaining = expires - time.monotonic()
                    self.results.put((key, (*cached[:4], remaining)))
                    continue
                del cache[key]
            if self.stopped.wait(max(0, next_request - time.monotonic())):
                return
            result = ([], [], primary_error)
            source = "LRCLIB"
            primary_missing = False
            if time.monotonic() >= primary_retry:
                try:
                    result = fetch_lyrics(key)
                    primary_error = result[2]
                except urllib.error.HTTPError as error:
                    primary_missing = error.code == 404
                    if not primary_missing:
                        primary_retry = time.monotonic() + retry_delay(error)
                    primary_error = ("LRCLIB: söz bulunamadı" if primary_missing else
                                     f"LRCLIB: HTTP {error.code}")
                    result = ([], [], primary_error)
                except Exception:
                    primary_retry = time.monotonic() + 30
                    primary_error = "LRCLIB: bağlantı kurulamadı"
                    result = ([], [], primary_error)
            delay = float("inf")
            if musixmatch_key and not result[0] and result[2] != "Enstrümantal parça":
                if time.monotonic() >= musixmatch_retry:
                    try:
                        matched = fetch_musixmatch(key, musixmatch_key)
                        if matched[0] or matched[1]:
                            result, source = matched, "Musixmatch"
                            musixmatch_error = ""
                    except MusixmatchError as error:
                        musixmatch_error = str(error)
                        # Invalid credentials/plan access should not be retried every track.
                        delay = 3600 if error.code in (401, 402, 403) else retry_delay(error)
                        musixmatch_retry = time.monotonic() + delay
                    except Exception:
                        musixmatch_error = "Musixmatch: yanıt işlenemedi"
                        musixmatch_retry = time.monotonic() + 30
            if not result[0] and not result[1] and result[2] != "Enstrümantal parça":
                if time.monotonic() >= fallback_retry:
                    try:
                        fallback = fetch_fallback(key)
                        if fallback[1]:
                            result, source = fallback, "lyrics.ovh"
                        else:
                            fallback_error = "lyrics.ovh: söz bulunamadı"
                    except urllib.error.HTTPError as error:
                        if error.code == 404:
                            fallback_error = "lyrics.ovh: söz bulunamadı"
                        else:
                            fallback_retry = time.monotonic() + retry_delay(error)
                            fallback_error = f"lyrics.ovh: HTTP {error.code}"
                    except Exception:
                        fallback_retry = time.monotonic() + 30
                        fallback_error = "lyrics.ovh: bağlantı kurulamadı"
                if not result[0] and not result[1]:
                    delay = max(30, primary_retry - time.monotonic(),
                                fallback_retry - time.monotonic())
                    if primary_missing and "bulunamadı" in result[2]:
                        delay = max(delay, 300)
                    errors = " · ".join(filter(None, (local_error, primary_error, musixmatch_error, fallback_error)))
                    result = ([], [], errors
                              + "; otomatik yeniden denenecek.")
            if result[1] and not result[0]:
                # Plain fallback must not prevent recovery to timed lyrics.
                delay = max(30, primary_retry - time.monotonic())
                if source == "Musixmatch":
                    delay = max(delay, 300)
            result = (*result, source, delay)
            # Never cache a transport error: reopening must not replay that error.
            if result[0] or result[1] or result[2] == "Enstrümantal parça":
                cache[key] = (time.monotonic() + delay, result)
                cache.move_to_end(key)
                while len(cache) > 32:
                    cache.popitem(last=False)
            next_request = time.monotonic() + 0.3
            self.results.put((key, result))

    def poll(self):
        while True:
            try:
                key, result = self.results.get_nowait()
            except queue.Empty:
                return
            if key == self.key:
                self.synced, self.plain, self.message = result[:3]
                self.source = result[3] if len(result) > 3 else "LRCLIB"
                self.next_retry = time.monotonic() + (result[4] if len(result) > 4 else float("inf"))

    def draw(self, screen, top, left, width, height, position):
        import curses

        self.poll()
        if width < 1 or height < 2:
            return

        def write(row, text, style=0):
            text = "".join(c if c.isprintable() else " " for c in text)
            try:
                screen.addnstr(row, left, text, width, style)
            except curses.error:
                pass

        label = "Sözler · " + self.source + (" · Canlı" if self.synced else " · Zamanlama yok" if self.plain else "")
        write(top, label, curses.A_DIM)
        available = max(1, height - 2)
        if self.source == "Musixmatch" and self.message and (self.synced or self.plain):
            write(top + height - 1, self.message, curses.A_DIM)
            available = max(1, available - 1)
        if not self.synced and not self.plain:
            lines = textwrap.wrap(self.message, width) or [""]
            if self.next_retry != float("inf"):
                seconds = max(0, int(self.next_retry - time.monotonic()) + 1)
                lines.extend(textwrap.wrap(f"Yeniden deneme: {seconds} sn · [s] Tekrar dene", width))
            for index, line in enumerate(lines[:available]):
                write(top + 2 + index, line)
            return
        active = active_line(self.synced, position) if self.synced else -1
        source = [line[1] for line in self.synced] if self.synced else self.plain
        rows, anchor = [], 0
        for index, line in enumerate(source):
            if index == active:
                anchor = len(rows)
            for part in textwrap.wrap(line, max(1, width - 2)) or [""]:
                rows.append((part, index == active))
        start = max(0, anchor - available // 2) if self.synced else self.offset
        start = min(start, max(0, len(rows) - available))
        if not self.synced:
            self.offset = start
        for index, (line, highlighted) in enumerate(rows[start:start + available]):
            write(top + 2 + index, ("› " if highlighted else "  ") + line,
                  curses.A_BOLD | curses.A_REVERSE if highlighted else curses.A_DIM)

    def close(self):
        self.stopped.set()
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(None)
