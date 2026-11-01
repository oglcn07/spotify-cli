"""Offline checks for local LRC imports, isolation, reload and highlighting."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import spotify
from watch_local_lyrics import import_lrc, load_local, lyrics_path, track_key
from watch_lyrics import Lyrics, lyric_position


class LocalLyricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch = patch('watch_local_lyrics.LYRICS_DIR', self.root / 'lyrics')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.key = ('Şarkı / ../../', 'Sanatçı', 'Albüm', 120)

    def file(self, text):
        path = self.root / 'source.lrc'
        path.write_text(text, encoding='utf-8')
        return path

    def test_import_roundtrip_bom_offset_and_safe_destination(self):
        source = self.file('\ufeff[offset:500]\n[00:01.25] Bir\n[00:03.50] İki')
        destination, count = import_lrc(source, self.key)
        self.assertEqual(count, 2)
        self.assertEqual(destination.parent, self.root / 'lyrics')
        self.assertEqual(load_local(self.key)[0], [(1.75, 'Bir'), (4.0, 'İki')])
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_versions_are_separate_but_duration_rounding_is_stable(self):
        self.assertNotEqual(lyrics_path(self.key), lyrics_path((*self.key[:2], 'Live', 120)))
        self.assertEqual(lyrics_path(self.key), lyrics_path((*self.key[:3], 121)))
        self.assertIsNone(load_local(self.key))

    def test_invalid_import_never_replaces_valid_file(self):
        source = self.file('[00:01] Original')
        destination, _ = import_lrc(source, self.key)
        for text in ('Plain lyrics', '[00:01]', 'x' * (1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                import_lrc(self.file(text), self.key)
            self.assertIn('Original', destination.read_text())
        self.assertEqual(len(list(destination.parent.iterdir())), 1)

    def test_worker_prefers_local_and_reload_reads_edited_file(self):
        import_lrc(self.file('[00:01] Bir\n[00:03] İki'), self.key)
        with patch('watch_lyrics.fetch_lyrics') as network:
            lyrics = Lyrics()
            try:
                state = dict(zip(('title', 'artist', 'album', 'mpris:length'), self.key))
                lyrics.request(state)
                result = lyrics.results.get(timeout=2)
                lyrics.results.put(result)
                lyrics.poll()
                self.assertEqual(lyrics.source, 'Yerel LRC')
                screen = Mock()
                lyrics.draw(screen, 2, 90, 30, 10, 3.1)
                self.assertTrue(any(c.args[2] == '› İki' for c in screen.addnstr.call_args_list))
                import_lrc(self.file('[00:01] Updated'), self.key)
                lyrics.request(state, force=True)
                result = lyrics.results.get(timeout=2)
                self.assertEqual(result[1][0], [(1.0, 'Updated')])
                network.assert_not_called()
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_position_tracks_fractional_timing_pause_seek_and_track_end(self):
        state = {'position': 3, 'position_precise': 3.25, 'status': 'Playing', 'mpris:length': 10}
        self.assertEqual(lyric_position(state, 100, 100.5), 3.75)
        state['status'] = 'Paused'
        self.assertEqual(lyric_position(state, 100, 105), 3.25)
        state.update(status='Playing', position_precise=1.0)
        self.assertEqual(lyric_position(state, 105, 105.5), 1.5)
        self.assertEqual(lyric_position(state, 105, 120), 10)
        self.assertEqual(lyric_position(None, 100, 110), 0)

    def test_import_command_only_reads_playback_and_stores_file(self):
        source = self.file('[00:01] Test')
        state = dict(zip(('title', 'artist', 'album', 'mpris:length'), self.key))
        with patch('spotify.sys.argv', ['spotify', 'lyrics', 'import', str(source)]), patch('spotify.read_watch_state', return_value=state), patch('spotify.control_player') as playback, patch('builtins.print'):
            spotify.main()
            self.assertEqual(load_local(self.key)[0], [(1.0, 'Test')])
            playback.assert_not_called()
        with self.assertRaises(ValueError):
            track_key(None)


if __name__ == '__main__':
    unittest.main()
