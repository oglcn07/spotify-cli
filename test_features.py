"""Offline regression checks for browsing, transport, pins and design controls."""

import curses
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

import spotify
import watch_pins
import watch_settings
from watch_browse import collection_page, parse_timestamp, seek_target
from test_watch_ui import Screen
import test_watch_ui


class FeatureTests(unittest.TestCase):
    def test_album_artist_and_playlist_pagination_handles_current_schema(self):
        sp = Mock()
        track = {'uri': 'spotify:track:test', 'type': 'track', 'name': 'Track'}
        sp.album_tracks.return_value = {'items': [track, None], 'next': 'next'}
        album = {'uri': 'spotify:album:test', 'type': 'album', 'name': 'Album'}
        self.assertEqual(collection_page(sp, {'item': album, 'offset': 20})['items'], [track])
        sp.album_tracks.assert_called_with(album['uri'], limit=10, offset=20)
        sp.artist_albums.return_value = {'items': [album], 'next': None}
        artist = {'uri': 'spotify:artist:test', 'type': 'artist'}
        self.assertEqual(collection_page(sp, {'item': artist})['items'], [album])
        sp._get.return_value = {'items': [{'item': track}, {'track': track}, None, {'item': None},
                                        {'item': {'uri': 'spotify:episode:x', 'type': 'episode'}},
                                        {'item': {**track, 'is_local': True}}]}
        playlist = {'uri': 'spotify:playlist:test', 'type': 'playlist'}
        self.assertEqual(collection_page(sp, {'item': playlist})['items'], [track, track])
        sp._get.assert_called_with('playlists/test/items', limit=10, offset=0)

    def test_seek_parsing_and_bounds(self):
        self.assertEqual(parse_timestamp('2:15'), 135)
        self.assertEqual(parse_timestamp('30'), 30)
        for value in ('2:60', '-10', '2:15:10', 'hello', ''):
            with self.assertRaises(ValueError):
                parse_timestamp(value)
        state = {'title': 'Track', 'position_precise': 3.25, 'mpris:length': 100}
        self.assertEqual(seek_target(state, delta=-5), 0)
        self.assertEqual(seek_target(state, delta=5), 8250)
        self.assertEqual(seek_target(state, target=200), 100000)
        with self.assertRaises(RuntimeError):
            seek_target(None, delta=5)

    def test_transport_uses_observed_modes_not_assumed_defaults(self):
        state = {'title': 'Track', 'position': 3, 'mpris:length': 100, 'shuffle': True, 'repeat': 'track'}
        with patch('spotify.read_watch_state', return_value=state), patch('spotify.soloist_ctl') as ctl:
            with patch('spotify.read_watch_state', side_effect=[state, {**state, 'shuffle': False}]):
                spotify.perform_transport({'action': 'shuffle'})
            ctl.assert_called_with('shuffle', 'off')
            with patch('spotify.read_watch_state', side_effect=[state, {**state, 'repeat': 'off'}]):
                spotify.perform_transport({'action': 'repeat'})
            ctl.assert_called_with('repeat', 'off')
            spotify.perform_transport({'action': 'seek', 'delta': 5})
            ctl.assert_called_with('seek', '8000')
        with patch('spotify.read_watch_state', return_value={}), patch('spotify.soloist_ctl') as ctl:
            with self.assertRaises(RuntimeError):
                spotify.perform_transport({'action': 'shuffle'})
            ctl.assert_not_called()

    def test_rejected_mode_change_does_not_report_success(self):
        with patch('spotify.read_watch_state', return_value={'shuffle': False}), patch('spotify.soloist_ctl'), patch('spotify.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'değişmedi'):
                spotify.perform_transport({'action': 'shuffle'})

    def test_pin_toggle_alias_and_invalid_uri(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(watch_pins, 'PINS_PATH', Path(folder) / 'pins.json'):
            item = {'uri': 'spotify:album:test', 'name': 'My album'}
            self.assertTrue(watch_pins.pin_item(item))
            watch_pins.pin_item({**item, 'name': 'Short name'})
            self.assertEqual(watch_pins.load_pins(), [{**item, 'name': 'Short name', 'type': 'album'}])
            self.assertFalse(watch_pins.pin_item(item, toggle=True))
            self.assertEqual(watch_pins.load_pins(), [])
            for uri in ('spotify:track:test', 'https://example.com', 'spotify:album:../../'):
                with self.assertRaises(ValueError):
                    watch_pins.pin_item({'uri': uri})

    def test_settings_validation_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(watch_settings, 'SETTINGS_PATH', Path(folder) / 'settings.json'):
            watch_settings.save_settings(design='classic', background_brightness=50, panel_width=42, lyrics_width=32)
            watch_settings.save_settings(volume=50)
            settings = watch_settings.load_settings()
            self.assertEqual(settings['background_brightness'], 50)
            self.assertEqual(settings['panel_width'], 42)
            watch_settings.save_settings(background_brightness=True, panel_width=1000, lyrics_width=-1)
            settings = watch_settings.load_settings()
            self.assertNotIn('background_brightness', settings)
            self.assertNotIn('panel_width', settings)
            self.assertEqual(settings['design'], 'classic')

    def test_settings_screen_edits_with_arrows_without_sending_playback_commands(self):
        screen = Screen([',', curses.KEY_RIGHT, curses.KEY_DOWN, curses.KEY_RIGHT,
                         curses.KEY_DOWN, curses.KEY_RIGHT, '\x1b', 'q'])
        worker, _, _, save = test_watch_ui.WatchUITests().run_watch(screen)
        save.assert_any_call(background_brightness=50)
        save.assert_any_call(panel_width=52)
        save.assert_any_call(lyrics_width=42)
        worker.jobs.put.assert_not_called()

    def test_help_scrolls_and_settings_quits(self):
        screen = Screen(['?', curses.KEY_NPAGE, curses.KEY_NPAGE, '?', ',', 'q'], height=24)
        test_watch_ui.WatchUITests().run_watch(screen)
        self.assertTrue(any('Favoriler izni' in frame for frame in screen.frames))

    def test_cancelled_search_does_not_reopen_results(self):
        worker = Mock(results=queue.Queue())
        response = {'query': 'A', 'type': 'track', 'offset': 0, 'next': False,
                    'items': [{'type': 'track', 'uri': 'spotify:track:test', 'name': 'Late result'}]}
        class DelayedScreen(Screen):
            def get_wch(self):
                key = super().get_wch()
                if key == '\x1b':
                    worker.results.put(('search', response, None, 0))
                return key
        screen = DelayedScreen(['/', 'A', '\n', '\x1b', 'q'])
        test_watch_ui.WatchUITests().run_watch(screen, worker)
        self.assertFalse(any('Late result' in frame for frame in screen.frames))

    def test_browse_stack_restores_search_and_paging_does_not_push_new_view(self):
        album = {'uri': 'spotify:album:test', 'name': 'Album result', 'type': 'album'}
        track = {'uri': 'spotify:track:test', 'name': 'Track inside album', 'type': 'track'}
        worker = Mock(results=queue.Queue())
        jobs = []
        def put(job):
            kind, value = job
            jobs.append(job)
            if kind == 'search':
                worker.results.put((kind, {**value, 'items': [album], 'next': False}, None, 0))
            elif kind == 'browse':
                worker.results.put((kind, {**value, 'items': [track], 'next': True}, None, 0))
        worker.jobs.put.side_effect = put
        screen = Screen(['/', '\t', 'A', '\n', 'o', ']', '\x1b', '\n', 'q'])
        test_watch_ui.WatchUITests().run_watch(screen, worker)
        self.assertTrue(any('Track inside album' in frame for frame in screen.frames))
        self.assertEqual(jobs[1][0], 'browse')
        self.assertTrue(jobs[1][1]['push'])
        self.assertFalse(jobs[2][1]['push'])
        self.assertEqual(jobs[-1], ('play', 'spotify:album:test'))


if __name__ == '__main__':
    unittest.main()
