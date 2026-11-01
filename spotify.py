#!/usr/bin/env python3

import sys
import json
import subprocess
import time
import queue
import threading
from pathlib import Path
import spotipy
from spotipy.oauth2 import SpotifyPKCE
from spotipy.exceptions import SpotifyException
from watch_config import client_id, token_cache_path, PrivateTokenCache, save_client_id, REDIRECT_URI
from watch_art import AlbumArt, cover_url
from watch_lyrics import Lyrics, lyric_position
from watch_local_lyrics import import_lrc, lyrics_path, track_key
from watch_browse import collection_page, parse_timestamp, seek_target
from watch_pins import load_pins, pin_item, COLLECTIONS
from watch_ui import island, lyrics_rect, classic_geometry
from watch_settings import COVER_MODES, load_settings, save_settings

SOLOIST = str(Path.home() / ".local/bin/soloist")
DEVICE_NAME = "Cano Terminal"
SOLOIST_ENV = Path.home() / ".config/soloist/soloist.env"


def soloist_ctl(*args, check=True):
    return subprocess.run(
        [SOLOIST, "ctl", *args], check=check,
        capture_output=True, text=True, timeout=2
    )


def control_player(action, *args):
    if action == "play-pause":
        state = read_watch_state()
        action = "pause" if state and state["status"] == "Playing" else "play"
    action = {"previous": "prev"}.get(action, action)
    return soloist_ctl(action, *args)


class WatchPKCE(SpotifyPKCE):
    def get_authorization_code(self, response=None):
        raise RuntimeError("Önce watch dışında spotify play ile giriş yap.")


def get_spotify(interactive=True, library=False):
    selected_client = client_id()
    auth = (SpotifyPKCE if interactive else WatchPKCE)(
        client_id=selected_client,
        redirect_uri=REDIRECT_URI,
        scope=("user-read-playback-state user-modify-playback-state" +
               (" user-library-read user-library-modify" if library else "")),
        cache_handler=PrivateTokenCache(cache_path=str(token_cache_path(selected_client))),
        open_browser=False
    )
    return spotipy.Spotify(
        auth_manager=auth,
        requests_timeout=15,
        retries=0
    )


def save_track(sp, uri):
    if not uri or not uri.startswith("spotify:track:"):
        raise RuntimeError("Beğenmek için çalan bir şarkı seç.")
    # Installed Spotipy has no public wrapper for Spotify's new library endpoint.
    sp._put("me/library", args={"uris": uri})


def read_queue(limit=50):
    result = soloist_ctl("queue", str(limit))
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def ensure_spotify_running():
    """Start the official windowless player; never launch desktop Spotify."""
    if not SOLOIST_ENV.is_file():
        raise RuntimeError(
            "Önce proje klasöründe .venv/bin/python setup_soloist.py ile Soloist anahtarını kaydet."
        )
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", "soloist.service"],
        capture_output=True, timeout=2
    )
    if result.returncode:
        subprocess.run(["systemctl", "--user", "start", "soloist.service"],
                       check=True, capture_output=True, text=True, timeout=10)
    for _ in range(20):
        result = soloist_ctl("status", check=False)
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("Soloist hazır değil; journalctl --user -u soloist -n 20 ile kontrol et.")


def wait_for_spotify_device(sp, timeout=45):
    print("⏳ Spotify cihazı bekleniyor...")

    for _ in range(timeout):

        try:
            devices = sp.devices()["devices"]

            device = next(
                (d for d in devices if d.get("name") == DEVICE_NAME
                 and d.get("id") and not d.get("is_restricted")),
                None
            )
            if device:
                return device

        except SpotifyException as e:
            if e.http_status != 404:
                raise

        time.sleep(1)

    return None


def play_song(query):
    ensure_spotify_running()
    sp = get_spotify()

    results = sp.search(q=query, type="track", limit=10)
    tracks = results["tracks"]["items"]

    if not tracks:
        print("Şarkı bulunamadı.")
        return

    # Şarkı adını ve sanatçıyı birlikte eşleştir
    import unicodedata

    def normalize(text):
        text = unicodedata.normalize("NFKD", text.casefold())
        return "".join(c for c in text if not unicodedata.combining(c))

    words = normalize(query).split()

    def score(track):
        title = normalize(track["name"])
        artist = normalize(" ".join(a["name"] for a in track["artists"]))
        combined = title + " " + artist
        return (
            sum(3 for w in words if w in title)
            + sum(1 for w in words if w in artist)
            - sum(2 for w in words if w not in combined)
        )

    track = max(tracks, key=score)
    uri = track["uri"]
    artist = ", ".join(a["name"] for a in track["artists"])

    print(f"🎵 {artist} - {track['name']}")

    device = wait_for_spotify_device(sp)

    if not device:
        print("Spotify 45 saniyede cihaz olarak görünmedi.")
        return

    sp.start_playback(
        device_id=device["id"],
        uris=[uri]
    )

    print(f"▶ Çalıyor: {device['name']}")


def play_collection(query, kind, shuffle=False):
    ensure_spotify_running()
    sp = get_spotify()

    results = sp.search(q=query, type=kind, limit=10)
    items = results[kind + "s"]["items"]

    if not items:
        print("Sonuç bulunamadı.")
        return

    import unicodedata

    def normalize(value):
        value = unicodedata.normalize("NFKD", value.casefold())
        return "".join(
            c for c in value if not unicodedata.combining(c)
        )

    words = normalize(query).split()

    def score(item):
        name = normalize(item["name"])
        artists = normalize(" ".join(
            a["name"] for a in item.get("artists", [])
        ))
        combined = name + " " + artists

        return (
            sum(3 for w in words if w in name)
            + sum(2 for w in words if w in artists)
            - sum(4 for w in words if w not in combined)
        )

    item = max(items, key=score)

    print(f"🎵 {item['name']}")
    if kind == "album":
        print("🎤 " + ", ".join(
            a["name"] for a in item["artists"]
        ))

    device = wait_for_spotify_device(sp)

    if not device:
        print("Spotify çalma cihazı bulunamadı.")
        return

    device_id = device["id"]

    # Shuffle ayarını önce uygula
    sp.shuffle(shuffle, device_id=device_id)

    sp.start_playback(
        device_id=device_id,
        context_uri=item["uri"]
    )

    show_playing_track(sp, device_id, item['uri'])

    print(
        f"▶ Çalıyor: {device['name']}"
        + (" | 🔀 Shuffle açık" if shuffle else "")
    )



def play_playlist(query, shuffle=False):
    ensure_spotify_running()
    sp = get_spotify()

    results = sp.search(q=query, type="playlist", limit=10)
    items = [
        item for item in results["playlists"]["items"]
        if item is not None
    ]

    if not items:
        print("Playlist bulunamadı.")
        return

    import unicodedata

    def normalize(value):
        value = unicodedata.normalize("NFKD", value.casefold())
        return "".join(
            c for c in value
            if not unicodedata.combining(c)
        )

    words = normalize(query).split()

    def score(item):
        name = normalize(item["name"])
        owner = normalize(
            (item.get("owner") or {}).get("display_name") or ""
        )
        combined = name + " " + owner

        return (
            sum(3 for w in words if w in name)
            + sum(1 for w in words if w in owner)
            - sum(4 for w in words if w not in combined)
        )

    playlist = max(items, key=score)

    owner = (
        (playlist.get("owner") or {}).get("display_name")
        or "Bilinmeyen kullanıcı"
    )

    print(f"🎶 Playlist: {playlist['name']}")
    print(f"👤 Oluşturan: {owner}")

    device = wait_for_spotify_device(sp)

    if not device:
        print("Spotify çalma cihazı bulunamadı.")
        return

    device_id = device["id"]

    sp.start_playback(
        device_id=device_id,
        context_uri=playlist["uri"]
    )

    sp.shuffle(shuffle, device_id=device_id)

    show_playing_track(sp, device_id, playlist['uri'])

    print(
        f"▶ Çalıyor: {device['name']}"
        + (" | 🔀 Shuffle açık" if shuffle else "")
    )




def show_playing_track(sp, device_id, expected_context=None):
    """Spotify'da gerçekten başlayan şarkıyı göster."""
    for _ in range(12):
        time.sleep(0.5)

        playback = sp.current_playback()

        if not playback or not playback.get("is_playing"):
            continue

        device = playback.get("device") or {}
        if device.get("id") != device_id:
            continue

        context = playback.get("context") or {}

        if expected_context and context.get("uri") != expected_context:
            continue

        track = playback.get("item")

        if not track or track.get("type") != "track":
            continue

        artist = ", ".join(
            a["name"] for a in track.get("artists", [])
        )

        album = (track.get("album") or {}).get("name", "Bilinmiyor")

        print()
        print("▶ Şimdi çalıyor:")
        print(f"🎵 {track['name']}")
        print(f"🎤 {artist}")
        print(f"💿 {album}")
        print(f"💻 Cihaz: {device.get('name', 'Bilinmiyor')}")
        return

    print("⏳ Çalan şarkı henüz doğrulanamadı.")


def entity_name(entity):
    return ((entity or {}).get("decorations") or {}).get("identity", {}).get("name", "")


def read_watch_state():
    """Read local Soloist playback, including its actual playlist context."""
    result = soloist_ctl("now", "--json", check=False)
    if result.returncode:
        return None
    try:
        raw = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    item = raw.get("item") or {}
    decorations = item.get("decorations") or {}
    position = raw.get("position") or {}
    elapsed_ms = position.get("position_ms", 0)
    if raw.get("status") == "playing" and position.get("timestamp_ms"):
        elapsed_ms += max(0, time.time() * 1000 - position["timestamp_ms"]) * position.get("speed", 1)
    context = raw.get("context") or {}
    prefix = {"playlist": "Playlist", "album": "Albüm", "artist": "Sanatçı"}.get(
        context.get("entity_type"), "Kaynak"
    )
    name = entity_name(context) or context.get("uri")
    return {
        "status": {"playing": "Playing", "paused": "Paused", "buffering": "Buffering"}.get(raw.get("status"), "Stopped"),
        "title": entity_name(item),
        "artist": ", ".join(entity_name(c.get("entity")) for c in decorations.get("creators", [])),
        "album": entity_name((decorations.get("parent") or {}).get("entity")),
        "position": max(0, int(elapsed_ms / 1000)),
        "position_precise": max(0, elapsed_ms / 1000),
        "mpris:length": max(0, int((decorations.get("playback") or {}).get("duration_ms", 0) / 1000)),
        "xesam:url": item.get("uri", ""),
        "context_label": f"{prefix}: {name}" if name else "Kaynak: Tek parça / bağlam yok",
        "cover_url": cover_url(item),
        "volume": raw.get("volume"),
        "shuffle": (raw.get("options") or {}).get("shuffle"),
        "repeat": (raw.get("options") or {}).get("repeat"),
        "context_item": {"uri": context.get("uri", ""), "type": context.get("entity_type", ""),
                         "name": name or ""},
    }


SEARCH_TYPES = ("track", "album", "artist", "playlist")
SEARCH_NAMES = {"track": "Şarkı", "album": "Albüm", "artist": "Sanatçı", "playlist": "Playlist"}


def search_items(sp, value):
    # Keep the old worker's string jobs working for callers/tests.
    if isinstance(value, str):
        return sp.search(q=value, type="track", limit=5)["tracks"]["items"]
    kind = value["type"]
    if kind not in SEARCH_TYPES:
        raise RuntimeError("Bilinmeyen arama türü.")
    offset = max(0, int(value.get("offset", 0)))
    page = sp.search(q=value["query"], type=kind, limit=10, offset=offset)[kind + "s"]
    return {**value, "offset": offset, "next": bool(page.get("next")),
            "items": [item for item in page.get("items", []) if item and item.get("uri")]}


def search_item_label(item):
    kind = item.get("type", "track")
    artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
    detail = ((item.get("owner") or {}).get("display_name", "") if kind == "playlist" else artists)
    duration = item.get("duration_ms")
    length = f" · {int(duration) // 60000}:{int(duration) // 1000 % 60:02d}" if duration else ""
    return f"{SEARCH_NAMES.get(kind, 'Şarkı')} · {item.get('name', '?')}" + (f" · {detail}" if detail else "") + length


def perform_transport(value):
    state = read_watch_state()
    action = value['action']
    if action == 'seek':
        milliseconds = seek_target(state, value.get('delta', 0), value.get('target'))
        soloist_ctl('seek', str(milliseconds))
        return 'Konum değiştirildi.'
    if action == 'shuffle':
        current = (state or {}).get('shuffle')
        setting = value.get('setting')
        if setting is None:
            if type(current) is not bool:
                raise RuntimeError('Karışık çalma durumu okunamadı.')
            setting = 'off' if current else 'on'
        if setting not in ('on', 'off'):
            raise RuntimeError('Karışık çalma: on veya off yaz.')
    elif action == 'repeat':
        current = (state or {}).get('repeat')
        setting = value.get('setting')
        if setting is None:
            modes = ('off', 'context', 'track')
            if current not in modes:
                raise RuntimeError('Tekrar durumu okunamadı.')
            setting = modes[(modes.index(current) + 1) % len(modes)]
        if setting not in ('off', 'context', 'track'):
            raise RuntimeError('Tekrar: off, context veya track yaz.')
    else:
        raise RuntimeError('Bilinmeyen oynatma işlemi.')
    soloist_ctl(action, setting)
    expected = setting == 'on' if action == 'shuffle' else setting
    for attempt in range(8):
        observed = read_watch_state()
        if observed and observed.get(action) == expected:
            return 'Oynatma modu değiştirildi.'
        if attempt < 7:
            time.sleep(0.1)
    raise RuntimeError('Bu bağlamda oynatma modu değişmedi; Spotify kısıtlaması olabilir. Albüm/playlist ile dene.')


class WatchAPI:
    """Serialize API work off the terminal thread; never draw from this worker."""

    def __init__(self):
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        sp = None
        library_sp = None
        retry_at = 0
        while True:
            job = self.jobs.get()
            if job is None or self.stopped.is_set():
                return
            kind, value = job
            if kind in ("search", "browse", "favorites", "like") and time.monotonic() < retry_at:
                self.results.put((kind, None, "Spotify istek sınırı; biraz bekle.",
                                  max(1, int(retry_at - time.monotonic()))))
                continue
            try:
                if kind in ("search", "browse") and sp is None:
                    sp = get_spotify(interactive=False)
                if kind == "search":
                    result = search_items(sp, value)
                elif kind == "browse":
                    result = collection_page(sp, value)
                elif kind == "transport":
                    result = perform_transport(value)
                elif kind == "play":
                    soloist_ctl("play", value)
                    result = "Seçim Spotify'a gönderildi."
                elif kind == "queue":
                    result = read_queue()
                elif kind == "enqueue":
                    soloist_ctl("add-to-queue", value)
                    result = "Şarkı sıraya eklendi."
                elif kind in ("favorites", "like"):
                    if library_sp is None:
                        library_sp = get_spotify(interactive=False, library=True)
                    if kind == "like":
                        save_track(library_sp, value)
                        result = "♥ Spotify beğenilenlerine eklendi."
                    else:
                        page = library_sp.current_user_saved_tracks(limit=20, offset=value)
                        result = {"tracks": [x["track"] for x in page["items"]
                                             if x.get("track") and x["track"].get("uri")],
                                  "offset": value, "next": bool(page.get("next"))}
                else:
                    raise RuntimeError("Bilinmeyen arka plan işlemi.")
                self.results.put((kind, result, None, 0))
            except Exception as error:
                delay = 30
                if isinstance(error, SpotifyException):
                    if error.http_status == 429:
                        try:
                            delay = max(30, int((error.headers or {}).get("Retry-After", 30)))
                        except (ValueError, TypeError):
                            pass
                        retry_at = time.monotonic() + delay
                    if kind == "browse" and error.http_status == 403:
                        self.results.put((kind, None, "Spotify bu koleksiyonu listelemeye izin vermiyor (403). Enter ile çalabilirsin.", delay))
                        continue
                    message = ("Favoriler izni gerekiyor: watch'tan çıkıp spotify login çalıştır."
                               if kind in ("favorites", "like") and error.http_status in (401, 403)
                               else f"Spotify API hatası ({error.http_status}).")
                elif isinstance(error, RuntimeError):
                    message = ("Favoriler için önce spotify login çalıştır."
                               if kind in ("favorites", "like") else str(error))
                else:
                    message = ("Favoriler alınamadı; spotify login ve bağlantını kontrol et."
                               if kind in ("favorites", "like") else
                               "İşlem tamamlanamadı; bağlantıyı ve Spotify oturumunu kontrol et.")
                self.results.put((kind, None, message, delay))

    def close(self):
        self.stopped.set()
        self.jobs.put(None)


def watch():
    """Live terminal player with local controls and background API search."""
    import curses

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("spotify watch için etkileşimli bir terminal aç.")
        return

    ensure_spotify_running()
    api = WatchAPI()
    art = AlbumArt()
    lyrics = Lyrics()
    preferences = load_settings()
    if "volume" in preferences:
        try:
            control_player("volume", str(preferences["volume"]))
        except (OSError, subprocess.SubprocessError):
            pass

    def run(screen):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.timeout(100)
        state = None
        message = ""
        next_refresh = 0
        sampled_at = time.monotonic()
        pending = None
        navigation_epoch = 0
        pending_epoch = 0
        help_offset = 0
        notice = ""
        mode = "normal"
        query = ""
        tracks = []
        selected = 0
        cover_modes = COVER_MODES
        cover_mode = cover_modes.index(preferences.get("cover_mode", "8-bit"))
        art_enabled = preferences.get("show_art", True)
        lyrics_enabled = preferences.get("show_lyrics", True)
        design = preferences.get("design", "islands")
        search_type = "track"
        search_page = None
        browse_page = None
        browse_stack = []
        settings_selected = 0
        brightness = preferences.get("background_brightness", 45)
        panel_width = preferences.get("panel_width", 50)
        preferred_lyrics_width = preferences.get("lyrics_width")
        queue_lines = []
        queue_offset = 0
        favorite_offset = 0
        favorite_next = False
        left_width = 0

        def remember(**changes):
            nonlocal notice
            try:
                save_settings(**changes)
            except OSError:
                notice = "Tercihler kaydedilemedi; klasör izinlerini kontrol et."

        def snapshot_view():
            return (mode, list(tracks), selected, search_page, browse_page,
                    favorite_offset, favorite_next)

        def submit(kind, value=None):
            nonlocal pending, pending_epoch, notice
            if pending is not None:
                notice = "İşlem sürüyor; birazdan tekrar dene."
                return
            api.jobs.put((kind, value))
            pending_epoch = navigation_epoch
            pending = kind
            notice = "İşlem sürüyor..."

        def write(row, text, style=0, full=False):
            height, width = screen.getmaxyx()
            if row >= height or width < 2:
                return
            text = "".join(c if c.isprintable() else " " for c in text)
            try:
                limit = width - 2 if full else left_width
                screen.addnstr(row, 3 if not full else 1, text, max(0, limit), style)
            except curses.error:
                pass

        def clock(seconds):
            return f"{seconds // 60}:{seconds % 60:02d}"

        while True:
            try:
                kind, result, error, delay = api.results.get_nowait()
            except queue.Empty:
                pass
            else:
                pending = None
                if kind in ("search", "browse", "favorites", "queue") and pending_epoch != navigation_epoch:
                    continue
                if error:
                    notice = error
                elif kind == "search":
                    if isinstance(result, dict):
                        search_page = result
                        tracks = result["items"]
                    else:
                        search_page = None
                        tracks = result
                    selected = 0
                    mode = "results"
                    notice = "" if tracks else "Sonuç bulunamadı. / ile yeniden ara."
                elif kind == "browse":
                    if result.get("push", True):
                        browse_stack.append(snapshot_view())
                    browse_page = result
                    tracks = result["items"]
                    selected = 0
                    mode = "browse"
                    notice = "" if tracks else "Bu sayfada gösterilebilir içerik yok."
                elif kind == "transport":
                    notice = result
                    next_refresh = 0
                elif kind == "favorites":
                    tracks = result["tracks"]
                    favorite_offset, favorite_next = result["offset"], result["next"]
                    selected = 0
                    mode = "favorites"
                    notice = "" if tracks else "Bu sayfada beğenilen şarkı yok."
                elif kind == "queue":
                    queue_lines = result
                    queue_offset = 0
                    mode = "queue"
                    notice = "" if result else "Kuyruk boş."
                elif kind == "browse":
                    result = collection_page(sp, value)
                elif kind == "transport":
                    result = perform_transport(value)
                elif kind == "play":
                    notice = result
                    mode = "normal"
                elif kind in ("enqueue", "like"):
                    notice = result

            if time.monotonic() >= next_refresh:
                try:
                    state = read_watch_state()
                    sampled_at = time.monotonic()
                    if state and type(state.get("volume")) is int:
                        if preferences.get("volume") != state["volume"]:
                            preferences["volume"] = state["volume"]
                            remember(volume=state["volume"])
                    message = "Soloist bağlantısı bekleniyor; Spotify Connect’ten Cano Terminal seç."
                except FileNotFoundError:
                    state = None
                    message = "Soloist bulunamadı; kurulumunu kontrol et."
                except subprocess.TimeoutExpired:
                    state = None
                    message = "Spotify yanıtı bekleniyor..."
                next_refresh = time.monotonic() + 1

            height, columns = screen.getmaxyx()
            rect = lyrics_rect(columns, height, lyrics_enabled, preferred_lyrics_width)
            layout_rect = lyrics_rect(columns, height, True, preferred_lyrics_width)
            info_width = min(panel_width, layout_rect[1] - 5) if layout_rect else min(panel_width, columns - 4)
            if mode in ("input", "seek_input", "results", "favorites", "browse", "pins", "queue"):
                info_width = min(panel_width, layout_rect[1] - 5) if layout_rect else min(panel_width, columns - 4)
            cover = None
            if design == "classic":
                info_width, cover, rect = classic_geometry(columns, height, art_enabled, lyrics_enabled, preferred_lyrics_width, panel_width)
            show_lyrics = rect is not None and mode not in ("help", "settings")
            left_width = max(0, info_width - 4)
            if show_lyrics:
                lyrics.request(state)
            lyrics.poll()
            art.request(state.get("cover_url", "") if state else "")
            art.poll()
            screen.erase()
            if design == "islands":
                if art_enabled and mode != "help":
                    art.draw(screen, 1, 0, columns - 1, max(1, height - 5),
                             cover_modes[cover_mode], background=True, brightness=brightness)
                island(screen, 1, 1, info_width, min(13, height - 5), "♫ Spotify · " + cover_modes[cover_mode])
                if mode in ("input", "seek_input", "results", "favorites", "browse", "pins", "queue"):
                    island(screen, 14, 1, info_width, max(0, height - 19), "Ara / Listeler")
                elif mode == "normal" and height >= 23:
                    island(screen, 15, 1, min(40, info_width), 4, "Keşfet")
                    write(16, "/ Ara · Tab ile tür seç")
                    write(17, "B Sabitlenenler · , Görünüm")
            else:
                write(1, "♫ Spotify · Klasik · " + cover_modes[cover_mode], curses.A_BOLD)
                if cover and mode != "help":
                    art.draw(screen, *cover, cover_modes[cover_mode])
            if state:
                status = {"Playing": "Çalıyor", "Paused": "Duraklatıldı",
                          "Stopped": "Durduruldu", "Buffering": "Yükleniyor"}.get(state["status"], "Bekleniyor")
                write(3, status + (f" · Ses %{state['volume']}" if state.get("volume") is not None else ""))
                shuffle_label = {True: "Açık", False: "Kapalı"}.get(state.get("shuffle"), "?")
                repeat_label = {"off": "Kapalı", "context": "Liste", "track": "Şarkı"}.get(state.get("repeat"), "?")
                write(4, f"Karışık: {shuffle_label} · Tekrar: {repeat_label}")
                write(5, state["title"] or "Parça bilgisi yok", curses.A_BOLD)
                write(6, state["artist"] or "Bilinmeyen sanatçı")
                write(7, state["album"] or "Bilinmeyen albüm")
                duration = state["mpris:length"]
                position = min(state["position"], duration) if duration else state["position"]
                width = max(1, min(44, left_width - 2))
                filled = min(width, int(width * position / duration)) if duration else 0
                write(9, "━" * filled + "─" * (width - filled))
                write(10, f"{clock(position)} / {clock(duration) if duration else '--:--'}")
                write(12, state["context_label"])

            else:
                write(4, message)
                write(6, "Soloist hazır olduğunda ekran otomatik güncellenir.")
            if mode == "input":
                prompt = SEARCH_NAMES[search_type] + " ara [Tab]: "
                space = max(1, left_width - len(prompt) - 1)
                write(15, prompt + query[-space:] + "▏")
            elif mode == "seek_input":
                write(15, "Git (2:15 veya saniye): " + query + "▏")
            elif mode in ("results", "favorites", "browse", "pins"):
                visible = max(1, height - 22)
                start = max(0, selected - visible + 1)
                if mode == "favorites":
                    write(15, f"♥ Beğenilenler · Sayfa {favorite_offset // 20 + 1} · [ / ] sayfa")
                if mode == "results" and search_page:
                    write(15, f"{SEARCH_NAMES[search_page['type']]} · Sayfa {search_page['offset'] // 10 + 1} · [ / ]")
                if mode == "browse" and browse_page:
                    write(15, f"{browse_page['item']['name']} · S{browse_page['offset'] // browse_page.get('limit', 10) + 1} [ / ]")
                elif mode == "pins":
                    write(15, "Sabitlenenler · o: Aç · b: Kaldır")
                for index in range(start, min(len(tracks), start + visible)):
                    track = tracks[index]
                    write(16 + index - start, ("> " if index == selected else "  ") + search_item_label(track),
                          curses.A_REVERSE if index == selected else 0)
            elif mode == "queue":
                write(15, "Sıradaki şarkılar · [k] Yenile · [↑/↓] Kaydır")
                for index, line in enumerate(queue_lines[queue_offset:queue_offset + max(1, height - 22)]):
                    write(16 + index, line)
            elif mode == "settings":
                screen.erase()
                write(1, "Görünüm ayarları · ↑/↓ seç · ←/→ değiştir · Esc geri", full=True)
                values = (f"Arka plan parlaklığı: %{brightness}", f"Bilgi kutusu genişliği: {panel_width}",
                          f"Söz kutusu genişliği: {preferred_lyrics_width or 'Otomatik'}")
                for index, value in enumerate(values):
                    write(4 + index * 2, value, curses.A_REVERSE if index == settings_selected else 0, full=True)
            elif mode == "help":
                screen.erase()
                help_lines = (
                    "♫ Spotify · Klavye yardımı", "",
                    "Space: Oynat / duraklat    n / p: Sonraki / önceki",
                    "/: Ara    Tab: Arama türü (şarkı/albüm/sanatçı/playlist)",
                    "↑ / ↓: Listede seç    [ / ]: Arama sonuçlarında sayfa",
                    "Enter: Seçileni çal    o: Albüm/sanatçı/playlist içine gir",
                    "Esc: Önceki liste    e: Şarkıyı sıraya ekle",
                    "← / →: 5 sn sar    Shift+←/→: 30 sn sar    g: Süreye git",
                    "z: Karışık çalma    r: Tekrar (kapalı/liste/şarkı)",
                    "b: Koleksiyonu sabitle/kaldır    B: Sabitlenenleri aç",
                    ",: Parlaklık ve kutu genişlikleri",
                    "k: Kuyruğu göster / yenile    f: Beğenilenleri göster",
                    "l: Çalanı beğen (listede seçileni beğenir)",
                    "[ / ]: Beğenilenlerde önceki / sonraki sayfa",
                    "+ / -: Sesi 5 puan değiştir",
                    "t: Tasarım (Adalar / Klasik); seçim hatırlanır",
                    "a: Kapak modu    v: Kapağı göster / gizle",
                    "s: Sağdaki söz panelini göster / gizle (en az 76 sütun)",
                    "PgUp / PgDn: Düz sözlerde kaydır",
                    "Kapak ve ses tercihleri sonraki açılışta hatırlanır.",
                    "Favoriler izni için: spotify login", "",
                    "Esc / ?: Geri    q / Ctrl+C: Çık (müzik devam eder)",
                )
                help_visible = max(1, height - 6)
                help_offset = min(help_offset, max(0, len(help_lines) - help_visible))
                for index, line in enumerate(help_lines[help_offset:help_offset + help_visible]):
                    write(index + 1, line, full=True)
            if show_lyrics:
                top, left, width, panel_height = rect
                if design == "islands":
                    island(screen, top, left, width, panel_height, "Sözler · [s] Gizle")
                lyrics.draw(screen, top + 1, left + 2, max(1, width - 4), max(2, panel_height - 2),
                            lyric_position(state, sampled_at, time.monotonic()))
            # Clear the footer so text remains readable over every cover.
            for footer_row in range(max(0, height - 4), height):
                write(footer_row, " " * max(0, columns - 2), full=True)
            write(max(0, height - 4), notice, full=True)
            if mode == "normal":
                help_text = "[Space] Oynat  [/] Ara  [k] Kuyruk  [f] Favoriler  [l] Beğen  [s] Sözler  [t] Tasarım  [?] Yardım  [q] Çık"
            elif mode == "help":
                help_text = "[↑/↓ PgUp/PgDn] Kaydır  [? / Esc] Geri  [q] Çık"
            elif mode == "settings":
                help_text = "[↑/↓] Seç  [←/→] Değiştir  [Esc] Geri"
            elif mode == "seek_input":
                help_text = "[Enter] Git  [Esc] Vazgeç"
            elif mode == "input":
                help_text = "[Tab] Tür: " + SEARCH_NAMES[search_type] + "  [Enter] Ara  [Esc] Vazgeç"
            else:
                help_text = "[↑/↓] Seç  [Enter] Çal  [o] Aç  [b] Sabitle  [Esc] Geri  [q] Çık"
            if columns < 100 and mode == "normal":
                help_text = "[Space] Oynat  [/] Ara  [s] Sözler  [t] Tasarım  [?] Yardım  [q] Çık"
            write(max(0, height - 2), help_text, full=True)
            if height < 24:
                write(0, "Tüm alanlar için terminali en az 24 satıra büyüt.")
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if mode == "help":
                if key in ("q", "Q"):
                    return
                if key in ("?", "\x1b"):
                    mode = "normal"
                elif key in (curses.KEY_UP, curses.KEY_PPAGE):
                    help_offset = max(0, help_offset - (5 if key == curses.KEY_PPAGE else 1))
                elif key in (curses.KEY_DOWN, curses.KEY_NPAGE):
                    help_offset += 5 if key == curses.KEY_NPAGE else 1
                continue
            if mode == "settings":
                if key in ("q", "Q"):
                    return
                if key in ("\x1b", ",", "\n", "\r"):
                    mode = "normal"
                elif key in (curses.KEY_UP, curses.KEY_DOWN):
                    settings_selected = (settings_selected + (1 if key == curses.KEY_DOWN else -1)) % 3
                elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                    step = 1 if key == curses.KEY_RIGHT else -1
                    if settings_selected == 0:
                        brightness = max(15, min(85, brightness + step * 5))
                        remember(background_brightness=brightness)
                    elif settings_selected == 1:
                        panel_width = max(32, min(68, panel_width + step * 2))
                        remember(panel_width=panel_width)
                    else:
                        preferred_lyrics_width = max(24, min(64, (preferred_lyrics_width or 40) + step * 2))
                        remember(lyrics_width=preferred_lyrics_width)
                continue
            if mode == "seek_input":
                if key == "\x1b":
                    mode = "normal"
                elif key in ("\n", "\r", curses.KEY_ENTER):
                    try:
                        target = parse_timestamp(query)
                    except ValueError as error:
                        notice = str(error)
                    else:
                        submit("transport", {"action": "seek", "target": target})
                        mode = "normal"
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    query = query[:-1]
                elif isinstance(key, str) and key in "0123456789:" and len(query) < 8:
                    query += key
                continue
            if mode == "input":
                if key == "\t":
                    search_type = SEARCH_TYPES[(SEARCH_TYPES.index(search_type) + 1) % len(SEARCH_TYPES)]
                elif key == "\x1b":
                    mode = "normal"
                elif key in ("\n", "\r", curses.KEY_ENTER):
                    if query.strip() and pending is None:
                        api.jobs.put(("search", {"query": query.strip(), "type": search_type, "offset": 0}))
                        pending = "search"
                        pending_epoch = navigation_epoch
                        mode = "normal"
                        notice = "Aranıyor..."
                    elif pending:
                        notice = "İşlem sürüyor; birazdan Enter'a tekrar bas."
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    query = query[:-1]
                elif isinstance(key, str) and key.isprintable() and len(query) < 200:
                    query += key
                continue
            if key in ("q", "Q"):
                return
            if key == "\x1b":
                navigation_epoch += 1
                notice = ""
                if mode == "browse" and browse_stack:
                    mode, tracks, selected, search_page, browse_page, favorite_offset, favorite_next = browse_stack.pop()
                else:
                    mode = "normal"
            elif key == "?":
                help_offset = 0
                mode = "normal" if mode == "help" else "help"
            elif key == "/":
                navigation_epoch += 1
                mode, query, notice = "input", "", ""
            elif key == ",":
                mode = "settings"
            elif key == "g":
                mode, query = "seek_input", ""
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_SLEFT, curses.KEY_SRIGHT):
                delta = 30 if key in (curses.KEY_SLEFT, curses.KEY_SRIGHT) else 5
                if key in (curses.KEY_LEFT, curses.KEY_SLEFT):
                    delta = -delta
                submit("transport", {"action": "seek", "delta": delta})
            elif key in ("z", "r"):
                submit("transport", {"action": "shuffle" if key == "z" else "repeat"})
            elif key == "B":
                navigation_epoch += 1
                tracks, selected, mode = load_pins(), 0, "pins"
                notice = "" if tracks else "Henüz sabitlenen koleksiyon yok; bir koleksiyon seçip b'ye bas."
            elif key == "b":
                item = (tracks[selected] if mode in ("results", "favorites", "browse", "pins") and tracks
                        else (browse_page['item'] if mode == "browse" and browse_page else
                              (state or {}).get("context_item", {})))
                try:
                    added = pin_item(item, toggle=True)
                    notice = "Koleksiyon sabitlendi." if added else "Sabitleme kaldırıldı."
                    if mode == "pins":
                        tracks = load_pins()
                        selected = max(0, min(selected, len(tracks) - 1))
                except (ValueError, OSError) as error:
                    notice = str(error)
            elif key == "o":
                if mode in ("results", "favorites", "browse", "pins") and tracks:
                    item = tracks[selected]
                    if item.get("type") in COLLECTIONS:
                        submit("browse", {"item": item, "offset": 0, "push": True})
                    else:
                        notice = "İçine girmek için bir albüm, sanatçı veya playlist seç."
            elif key == "s":
                lyrics_enabled = not lyrics_enabled
                remember(show_lyrics=lyrics_enabled)
                if lyrics_enabled:
                    lyrics.request(state, force=True)
                    if not lyrics_rect(columns, height, True):
                        notice = "Söz paneli için terminali en az 76 sütun ve 18 satıra büyüt."
            elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                lyrics.offset = max(0, lyrics.offset + (-5 if key == curses.KEY_PPAGE else 5))
            elif key == "t":
                design = "classic" if design == "islands" else "islands"
                remember(design=design)
            elif key == "a":
                cover_mode = (cover_mode + 1) % len(cover_modes)
                remember(cover_mode=cover_modes[cover_mode])
            elif key == "v":
                art_enabled = not art_enabled
                remember(show_art=art_enabled)
            elif key == "k":
                submit("queue")
            elif key == "f":
                submit("favorites", 0)
            elif mode == "results" and search_page and key in ("[", "]"):
                offset = search_page["offset"]
                if (key == "[" and offset) or (key == "]" and search_page["next"]):
                    submit("search", {"query": search_page["query"], "type": search_page["type"],
                                      "offset": max(0, offset + (-10 if key == "[" else 10))})
            elif mode == "browse" and browse_page and key in ("[", "]"):
                offset = browse_page["offset"]
                if (key == "[" and offset) or (key == "]" and browse_page["next"]):
                    submit("browse", {"item": browse_page["item"], "push": False,
                                      "offset": max(0, offset + (-browse_page.get("limit", 10) if key == "[" else browse_page.get("limit", 10)))})
            elif mode == "favorites" and key in ("[", "]"):
                if key == "[" and favorite_offset:
                    submit("favorites", max(0, favorite_offset - 20))
                elif key == "]" and favorite_next:
                    submit("favorites", favorite_offset + 20)
            elif mode == "queue" and key in (curses.KEY_UP, curses.KEY_DOWN):
                queue_offset = max(0, min(max(0, len(queue_lines) - max(1, height - 22)),
                                         queue_offset + (1 if key == curses.KEY_DOWN else -1)))
            elif mode in ("results", "favorites", "browse", "pins") and key in (curses.KEY_UP, curses.KEY_DOWN):
                selected = max(0, min(len(tracks) - 1, selected + (1 if key == curses.KEY_DOWN else -1)))
            elif mode in ("results", "favorites", "browse", "pins") and key in ("\n", "\r", curses.KEY_ENTER):
                if tracks and pending is None:
                    api.jobs.put(("play", tracks[selected]["uri"]))
                    pending = "play"
                    notice = "Spotify'a gönderiliyor..."
                elif pending:
                    notice = "İşlem sürüyor; birazdan tekrar dene."
            elif key in ("e", "l"):
                uri = (tracks[selected]["uri"] if mode in ("results", "favorites", "browse", "pins") and tracks
                       else (state or {}).get("xesam:url", ""))
                if uri.startswith("spotify:track:"):
                    submit("enqueue" if key == "e" else "like", uri)
                else:
                    notice = "Beğenme ve sıraya ekleme için bir şarkı seç; albüm/sanatçı/playlist desteklenmiyor."
            elif key in ("+", "=", "-"):
                current_volume = (state or {}).get("volume")
                if type(current_volume) is int:
                    volume = max(0, min(100, current_volume + (-5 if key == "-" else 5)))
                    try:
                        control_player("volume", str(volume))
                        state["volume"] = volume
                        preferences["volume"] = volume
                        remember(volume=volume)
                        next_refresh = 0
                    except (OSError, subprocess.SubprocessError):
                        notice = "Ses değiştirilemedi; Soloist bağlantısını kontrol et."
            elif key in (" ", "n", "p"):
                action = {" ": "play-pause", "n": "next", "p": "previous"}[key]
                try:
                    control_player(action)
                    notice = ""
                    next_refresh = 0
                except (OSError, subprocess.SubprocessError):
                    notice = "Soloist kontrol edilemedi; servis çalışıyor mu?"

    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        art.close()
        lyrics.close()


def main():
    if len(sys.argv) < 2:
        print("Kullanım: spotify {play|pause|resume|next|prev|now|volume|watch|queue|login|lyrics|seek|shuffle|repeat|pins|pin|unpin|configure}")
        return

    command = sys.argv[1].lower()
    args = sys.argv[2:]
    if command in ("play", "pause", "resume", "toggle", "next", "prev", "previous", "volume"):
        ensure_spotify_running()

    if command == "play":
        if not args:
            control_player("play")
        else:
            kind = "track"
            shuffle = False
            query_parts = []

            for arg in args:
                if arg in ("--album", "-album"):
                    kind = "album"
                elif arg in ("--artist", "-artist"):
                    kind = "artist"
                elif arg in ("--playlist", "-playlist"):
                    kind = "playlist"
                elif arg == "--shuffle":
                    shuffle = True
                else:
                    query_parts.append(arg)

            query = " ".join(query_parts).strip()

            if not query:
                print("Aranacak şarkı, albüm veya sanatçı yaz.")
                return

            if kind == "track":
                play_song(query)
            elif kind == "playlist":
                play_playlist(query, shuffle)
            else:
                play_collection(query, kind, shuffle)

    elif command in ("seek", "shuffle", "repeat"):
        ensure_spotify_running()
        value = {"action": command}
        if command == "seek":
            if len(args) != 1:
                print("Kullanım: spotify seek 2:15")
                return
            value["target"] = parse_timestamp(args[0])
        elif args:
            value["setting"] = args[0].lower()
        print(perform_transport(value))

    elif command in ("pins", "pinler"):
        pins = load_pins()
        for index, item in enumerate(pins, 1):
            print(f"{index}. {item['name']} · {item['uri']}")
        if not pins:
            print("Sabitlenen koleksiyon yok. Watch'ta bir koleksiyon seçip b'ye bas.")

    elif command in ("pin", "unpin"):
        if not args:
            print("Kullanım: spotify pin spotify:album:ID Kısa Ad | spotify unpin URI")
            return
        pin_item({"uri": args[0], "name": " ".join(args[1:]) or args[0]}, remove=command == "unpin")
        print("Koleksiyon sabitlendi." if command == "pin" else "Sabitleme kaldırıldı.")

    elif command == "watch":
        watch()

    elif command == "lyrics":
        if not args or args == ["path"]:
            print(lyrics_path(track_key(read_watch_state())))
        elif len(args) == 2 and args[0] == "import":
            key = track_key(read_watch_state())
            destination, count = import_lrc(Path(args[1]).expanduser(), key)
            print(f"✓ {key[1]} - {key[0]}: {count} zamanlı satır kaydedildi.")
            print(destination)
            print("Watch'ta s ile söz ekranını yeniden aç; aktif satır takip edilir.")
        else:
            print("Kullanım: spotify lyrics path | spotify lyrics import dosya.lrc")

    elif command == "configure":
        print("Kendi uygulamanı oluştur: https://developer.spotify.com/dashboard")
        print(f"Redirect URI: {REDIRECT_URI}")
        save_client_id(input("Web API Client ID (Client Secret değil): ").strip())
        print("✓ Client ID kaydedildi. Hesabını bağlamak için spotify login çalıştır.")

    elif command == "login":
        print("Favorileri okumak ve şarkı beğenmek için Spotify iznini tamamla.")
        sp = get_spotify(library=True)
        sp.current_user_saved_tracks(limit=1)
        print("✓ Spotify favorileri hazır. spotify watch ile devam edebilirsin.")

    elif command == "queue":
        ensure_spotify_running()
        print("\n".join(read_queue()) or "Kuyruk boş.")

    elif command == "pause":
        control_player("pause")

    elif command == "resume":
        control_player("play")

    elif command == "toggle":
        control_player("play-pause")

    elif command == "next":
        control_player("next")
        print("⏭ Sonraki şarkıya geçildi!")

        for _ in range(12):
            time.sleep(0.25)

            state = read_watch_state()
            if state and state["title"]:
                print()
                print(f"🎵 {state['title']}")
                print(f"🎤 {state['artist']}")
                print(f"💿 {state['album']}")
                break

        else:
            print("⏳ Yeni şarkı bilgisi alınamadı.")

    elif command in ("prev", "previous"):
        control_player("previous")

    elif command == "now":
        ensure_spotify_running()
        state = read_watch_state()
        if state:
            print(f"🎵 {state['artist']} - {state['title']}")
        else:
            print("Önce Spotify Connect üzerinden Cano Terminal cihazını bağla.")

    elif command == "volume":
        if not args:
            print("Örnek: spotify volume 50")
            return

        volume = int(args[0])
        if not 0 <= volume <= 100:
            print("Ses seviyesi 0-100 arasında olmalı.")
            return

        control_player("volume", str(volume))
        try:
            save_settings(volume=volume)
        except OSError:
            print("Ses değişti ama tercih dosyasına kaydedilemedi.")

    else:
        print(f"Bilinmeyen komut: {command}")

if __name__ == "__main__":
    try:
        main()
    except SpotifyException as e:
        if e.http_status == 429:
            print("Spotify API rate limit (429). Bir süre bekle.")
        else:
            print(f"Spotify API hatası: {e}")
    except subprocess.CalledProcessError:
        print("Soloist servisine bağlanılamadı.")
    except Exception as e:
        print(f"Hata: {e}")
