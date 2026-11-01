"""Offline regression checks for the windowless player integration."""

import json
import subprocess
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import spotify
import watch_settings
from watch_art import AlbumArt, cover_url, terminal_color
from PIL import Image


def entity(name, **decorations):
    return {"decorations": {"identity": {"name": name}, **decorations}}


class SoloistTests(unittest.TestCase):
    def test_terminal_color_keeps_neutral_grays(self):
        self.assertEqual(terminal_color((128, 128, 128)), 244)
        self.assertEqual(terminal_color((95, 135, 175)), 67)

    def test_detailed_pairs_do_not_alias_with_extended_terminal(self):
        import curses
        art = AlbumArt()
        try:
            # Bright colors used to produce pair IDs far above color_pair's 255 limit.
            art.image = Image.new("RGB", (96, 96), (240, 210, 180))
            with patch("curses.has_colors", return_value=True), patch.object(curses, "COLORS", 256, create=True), patch.object(curses, "COLOR_PAIRS", 65536, create=True), patch("curses.init_pair") as init, patch("curses.color_pair", return_value=0) as attr:
                art.draw(Mock(), 4, 63, 50, 20, mode="16-bit")
                self.assertTrue(all(1 <= c.args[0] <= 225 for c in init.call_args_list))
                self.assertTrue(all(1 <= c.args[0] <= 225 for c in attr.call_args_list))
                self.assertEqual(init.call_args.args[1], terminal_color((240, 210, 180)))
                init.reset_mock()
                attr.reset_mock()
                art.draw(Mock(), 4, 63, 50, 20, mode="Glitch")
                self.assertTrue(any(c.args[0] > 255 for c in init.call_args_list))
                self.assertTrue(all(c.args[0] < 256 for c in attr.call_args_list))
        finally:
            art.close()
            art.thread.join(timeout=2)

    def test_cover_url_prefers_medium_art_and_falls_back_to_album(self):
        album = entity("Albüm", visual_identity={"cover": [
            {"url": "https://example.com/large.jpg", "size": "large"},
            {"url": "https://example.com/medium.jpg", "size": "default"},
        ]})
        item = entity("Şarkı", parent={"entity": album})
        self.assertEqual(cover_url(item), "https://example.com/medium.jpg")
        self.assertEqual(cover_url({}), "")

    def test_cover_loader_ignores_stale_result_and_reuses_cached_image(self):
        image = Image.new("RGB", (96, 96), "red")
        with patch("watch_art.download_cover", return_value=image) as download:
            art = AlbumArt()
            try:
                art.request("first")
                first = art.results.get(timeout=2)
                art.request("second")
                second = art.results.get(timeout=2)
                art.results.put(first)
                art.poll()
                self.assertIsNone(art.image)
                art.results.put(second)
                art.poll()
                self.assertIs(art.image, image)
                art.request("first")
                art.results.get(timeout=2)
                self.assertEqual(download.call_count, 2)
            finally:
                art.close()
                art.thread.join(timeout=2)
            self.assertFalse(art.thread.is_alive())

    def test_failed_cover_does_not_break_player(self):
        with patch("watch_art.download_cover", side_effect=OSError("offline")):
            art = AlbumArt()
            try:
                art.request("missing")
                result = art.results.get(timeout=2)
                art.results.put(result)
                art.poll()
                self.assertIsNone(art.image)
                self.assertEqual(art.message, "Kapak alınamadı")
            finally:
                art.close()
                art.thread.join(timeout=2)

    def test_art_fits_panel_and_supports_ascii(self):
        art = AlbumArt()
        screen = Mock()
        try:
            art.image = Image.new("RGB", (96, 96), "white")
            art.colors = False
            art.draw(screen, 4, 63, 50, 20, mode="ASCII")
            self.assertEqual(screen.addstr.call_count, 400)
            for call in screen.addstr.call_args_list:
                row, col, text, _ = call.args
                self.assertLess(row, 24)
                self.assertGreaterEqual(col, 63)
                self.assertLessEqual(col + len(text), 113)
                self.assertEqual(text, "@@")
            screen.reset_mock()
            art.draw(screen, 4, 63, 10, 5)
            screen.addstr.assert_not_called()
        finally:
            art.close()
            art.thread.join(timeout=2)

    def test_detailed_art_and_mode_switch_with_limited_color_pairs(self):
        import curses
        art = AlbumArt()
        screen = Mock()
        try:
            art.image = Image.new("RGB", (96, 96), (100, 160, 210))
            with patch("curses.has_colors", return_value=True), patch.object(curses, "COLORS", 256, create=True), patch.object(curses, "COLOR_PAIRS", 256, create=True), patch("curses.init_pair") as init, patch("curses.color_pair", return_value=0):
                art.draw(screen, 4, 63, 50, 20, mode="16-bit")
                self.assertEqual(screen.addstr.call_count, 800)
                self.assertTrue(all(c.args[2] == "▀" for c in screen.addstr.call_args_list))
                self.assertTrue(all(c.args[0] < 256 for c in init.call_args_list))
                screen.reset_mock()
                art.draw(screen, 4, 63, 50, 20, mode="8-bit")
                self.assertEqual(screen.addstr.call_count, 400)
                self.assertTrue(all(c.args[2] == "  " for c in screen.addstr.call_args_list))
        finally:
            art.close()
            art.thread.join(timeout=2)

    def test_snapshot_and_playlist_from_local_player(self):
        item = entity(
            "Şarkı", playback={"duration_ms": 210000},
            creators=[{"entity": entity("Sanatçı")}],
            parent={"entity": entity("Albüm")},
        )
        item["uri"] = "spotify:track:test"
        context = entity("Cano Mix")
        context["entity_type"] = "playlist"
        raw = {"status": "playing", "item": item, "context": context,
               "position": {"position_ms": 45000, "timestamp_ms": 100000, "speed": 1}}
        response = subprocess.CompletedProcess([], 0, json.dumps(raw))
        with patch("spotify.soloist_ctl", return_value=response), patch("spotify.time.time", return_value=102):
            state = spotify.read_watch_state()
        self.assertEqual(state["position"], 47)
        self.assertEqual(state["mpris:length"], 210)
        self.assertEqual(state["artist"], "Sanatçı")
        self.assertEqual(state["album"], "Albüm")
        self.assertEqual(state["context_label"], "Playlist: Cano Mix")

    def test_disconnected_and_empty_snapshot(self):
        with patch("spotify.soloist_ctl", return_value=subprocess.CompletedProcess([], 3, "")):
            self.assertIsNone(spotify.read_watch_state())
        with patch("spotify.soloist_ctl", return_value=subprocess.CompletedProcess([], 0, "{}")):
            self.assertEqual(spotify.read_watch_state()["status"], "Stopped")

    def test_toggle_and_previous_use_local_control(self):
        with patch("spotify.read_watch_state", return_value={"status": "Playing"}), patch("spotify.soloist_ctl") as ctl:
            spotify.control_player("play-pause")
            ctl.assert_called_once_with("pause")
        with patch("spotify.read_watch_state", return_value={"status": "Paused"}), patch("spotify.soloist_ctl") as ctl:
            spotify.control_player("play-pause")
            ctl.assert_called_once_with("play")
        with patch("spotify.soloist_ctl") as ctl:
            spotify.control_player("previous")
            ctl.assert_called_once_with("prev")

    def test_worker_search_and_play_without_desktop_launch(self):
        sp = Mock()
        sp.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:test"}]}}
        with patch("spotify.get_spotify", return_value=sp), patch("spotify.soloist_ctl") as ctl:
            worker = spotify.WatchAPI()
            try:
                worker.jobs.put(("search", "şarkı"))
                kind, tracks, error, _ = worker.results.get(timeout=2)
                self.assertEqual(kind, "search")
                self.assertIsNone(error)
                worker.jobs.put(("play", tracks[0]["uri"]))
                self.assertIsNone(worker.results.get(timeout=2)[2])
                ctl.assert_called_once_with("play", "spotify:track:test")
            finally:
                worker.close()
                worker.thread.join(timeout=2)
            self.assertFalse(worker.thread.is_alive())

    def test_missing_key_does_not_launch_any_player(self):
        with patch("spotify.SOLOIST_ENV") as env, patch("spotify.subprocess.run") as run:
            env.is_file.return_value = False
            with self.assertRaisesRegex(RuntimeError, "setup_soloist"):
                spotify.ensure_spotify_running()
            run.assert_not_called()

    def test_volume_command_keeps_percentage_units(self):
        with patch("spotify.sys.argv", ["spotify", "volume", "50"]), patch("spotify.ensure_spotify_running"), patch("spotify.save_settings") as save, patch("spotify.soloist_ctl") as ctl:
            spotify.main()
            ctl.assert_called_once_with("volume", "50")
            save.assert_called_once_with(volume=50)

    def test_settings_validate_and_preserve_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(watch_settings, "SETTINGS_PATH", Path(folder) / "preferences.json"):
            path = watch_settings.SETTINGS_PATH
            path.write_text('[]')
            self.assertEqual(watch_settings.load_settings(), {})
            path.write_text('{broken')
            self.assertEqual(watch_settings.load_settings(), {})
            path.write_text('{"volume": true, "cover_mode": "unknown", "show_art": "yes"}')
            self.assertEqual(watch_settings.load_settings(), {})
            watch_settings.save_settings(cover_mode="Glitch", show_art=False)
            watch_settings.save_settings(volume=72)
            self.assertEqual(watch_settings.load_settings(),
                             {"cover_mode": "Glitch", "show_art": False, "volume": 72})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_queue_favorites_and_like_worker(self):
        sp = Mock()
        sp.current_user_saved_tracks.return_value = {
            "items": [{"track": {"uri": "spotify:track:test"}}, {"track": None}], "next": "next-page"}
        with patch("spotify.get_spotify", return_value=sp) as auth, patch("spotify.soloist_ctl", return_value=subprocess.CompletedProcess([], 0, "  1. Şarkı\n")) as ctl:
            worker = spotify.WatchAPI()
            try:
                worker.jobs.put(("queue", None))
                self.assertEqual(worker.results.get(timeout=2)[1], ["1. Şarkı"])
                worker.jobs.put(("enqueue", "spotify:track:test"))
                self.assertIsNone(worker.results.get(timeout=2)[2])
                ctl.assert_called_with("add-to-queue", "spotify:track:test")
                worker.jobs.put(("favorites", 20))
                result = worker.results.get(timeout=2)[1]
                self.assertEqual(result["offset"], 20)
                self.assertTrue(result["next"])
                self.assertEqual(len(result["tracks"]), 1)
                auth.assert_called_once_with(interactive=False, library=True)
                worker.jobs.put(("like", "spotify:track:test"))
                self.assertIsNone(worker.results.get(timeout=2)[2])
                sp._put.assert_called_once_with("me/library", args={"uris": "spotify:track:test"})
            finally:
                worker.close()
                worker.thread.join(timeout=2)

    def test_like_rejects_non_track_without_api_write(self):
        sp = Mock()
        with self.assertRaises(RuntimeError):
            spotify.save_track(sp, "spotify:album:test")
        sp._put.assert_not_called()

    def test_library_auth_failure_does_not_break_local_queue(self):
        with patch("spotify.get_spotify", side_effect=RuntimeError("login")), patch("spotify.read_queue", return_value=["1. Şarkı"]):
            worker = spotify.WatchAPI()
            try:
                worker.jobs.put(("favorites", 0))
                self.assertIn("spotify login", worker.results.get(timeout=2)[2])
                worker.jobs.put(("queue", None))
                self.assertEqual(worker.results.get(timeout=2)[1], ["1. Şarkı"])
            finally:
                worker.close()
                worker.thread.join(timeout=2)

    def test_watch_preferences_help_and_volume_keys(self):
        screen = Mock()
        screen.getmaxyx.return_value = (28, 120)
        screen.get_wch.side_effect = ["?", "?", "s", "s", "a", "v", "+", "q"]
        state = {"status": "Playing", "title": "Şarkı", "artist": "Sanatçı", "album": "Albüm",
                 "position": 5, "mpris:length": 100, "context_label": "Kaynak", "volume": 70}
        with patch("spotify.sys.stdin.isatty", return_value=True), patch("spotify.sys.stdout.isatty", return_value=True), patch("spotify.ensure_spotify_running"), patch("spotify.WatchAPI"), patch("spotify.AlbumArt"), patch("spotify.Lyrics"), patch("spotify.load_settings", return_value={"cover_mode": "Glitch", "volume": 70}), patch("spotify.save_settings") as save, patch("spotify.control_player") as ctl, patch("spotify.read_watch_state", return_value=state), patch("curses.curs_set"), patch("curses.wrapper", side_effect=lambda callback: callback(screen)):
            # Use a real empty results queue rather than Mock's infinite results.
            import queue
            spotify.WatchAPI.return_value.results = queue.Queue()
            spotify.watch()
            spotify.Lyrics.return_value.draw.assert_called()
            spotify.Lyrics.return_value.close.assert_called_once()
            ctl.assert_any_call("volume", "70")
            ctl.assert_any_call("volume", "75")
            save.assert_any_call(cover_mode="ASCII")
            save.assert_any_call(show_art=False)
            save.assert_any_call(volume=75)
            self.assertTrue(any("Klavye yardımı" in str(call) for call in screen.addnstr.call_args_list))


if __name__ == "__main__":
    unittest.main()
