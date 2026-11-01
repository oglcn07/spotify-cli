"""Regression checks for backdrop islands, lyrics toggle, and typed search."""

import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
import spotify
import watch_settings
from watch_art import AlbumArt
from watch_ui import island, lyrics_rect, classic_geometry


class Screen:
    def __init__(self, keys, height=30, width=120):
        self.keys = iter(keys)
        self.height, self.width = height, width
        self.frames = []
        self.erase()

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.buffer = [[' '] * self.width for _ in range(self.height)]

    def addnstr(self, row, col, text, limit, style=0):
        if not 0 <= row < self.height or not 0 <= col < self.width:
            return
        for index, char in enumerate(text[:limit]):
            if col + index < self.width:
                self.buffer[row][col + index] = char

    def addstr(self, row, col, text, style=0):
        self.addnstr(row, col, text, len(text), style)

    def refresh(self):
        self.frames.append('\n'.join(''.join(row) for row in self.buffer))

    def get_wch(self):
        return next(self.keys)

    def timeout(self, value):
        pass


class WatchUITests(unittest.TestCase):
    def test_background_is_centered_square_and_keeps_normal_pairs_below_256(self):
        import curses
        art = AlbumArt()
        art.image = Image.new('RGB', (96, 96), (100, 170, 230))
        try:
            for mode in ('8-bit', '16-bit', 'ASCII'):
                screen = Mock()
                with patch('curses.has_colors', return_value=True), patch.object(curses, 'COLORS', 256, create=True), patch.object(curses, 'COLOR_PAIRS', 65536, create=True), patch('curses.init_pair') as init, patch('curses.color_pair', return_value=0) as pair:
                    art.draw(screen, 0, 0, 119, 26, mode, background=True)
                calls = screen.addstr.call_args_list
                self.assertEqual(max(c.args[0] for c in calls), 25)
                self.assertEqual(min(c.args[1] for c in calls), 33)
                self.assertEqual(max(c.args[1] + len(c.args[2]) for c in calls), 85)
                self.assertTrue(all(c.args[1] + len(c.args[2]) <= 119 for c in calls))
                self.assertTrue(all(0 < c.args[0] < 256 for c in init.call_args_list))
                self.assertTrue(all(0 < c.args[0] < 256 for c in pair.call_args_list))
        finally:
            art.close()
            art.thread.join(timeout=2)

    def test_island_erases_background_without_touching_other_regions(self):
        screen = Screen([], 24, 80)
        screen.buffer = [['x'] * 80 for _ in range(24)]
        island(screen, 1, 2, 30, 10, 'Bilgiler')
        self.assertEqual(screen.buffer[5][5], ' ')
        self.assertEqual(screen.buffer[1][2], '╭')
        self.assertEqual(screen.buffer[5][50], 'x')
        self.assertIsNone(lyrics_rect(70, 24, True))
        self.assertIsNone(lyrics_rect(120, 24, False))

    def test_typed_search_filters_nulls_and_preserves_paging(self):
        sp = Mock()
        for kind in spotify.SEARCH_TYPES:
            item = {'type': kind, 'name': 'Sonuç', 'uri': f'spotify:{kind}:test'}
            sp.search.return_value = {kind + 's': {'items': [None, item, {}], 'next': 'next-page'}}
            result = spotify.search_items(sp, {'query': 'Şarkı', 'type': kind, 'offset': 10})
            self.assertEqual(result['items'], [item])
            self.assertTrue(result['next'])
            sp.search.assert_called_with(q='Şarkı', type=kind, limit=10, offset=10)
            self.assertIn(spotify.SEARCH_NAMES[kind], spotify.search_item_label(item))

    def run_watch(self, screen, worker=None, show_lyrics=True, design="islands"):
        state = {'status': 'Paused', 'title': 'Parça', 'artist': 'Sanatçı', 'album': 'Albüm',
                 'position': 5, 'mpris:length': 100, 'context_label': 'Kaynak', 'volume': 70}
        worker = worker or Mock(results=queue.Queue())
        with patch('spotify.sys.stdin.isatty', return_value=True), patch('spotify.sys.stdout.isatty', return_value=True), patch('spotify.ensure_spotify_running'), patch('spotify.WatchAPI', return_value=worker), patch('spotify.AlbumArt') as art, patch('spotify.Lyrics') as lyrics, patch('spotify.load_settings', return_value={'show_lyrics': show_lyrics, 'design': design}), patch('spotify.save_settings') as save, patch('spotify.read_watch_state', return_value=state), patch('curses.curs_set'), patch('curses.wrapper', side_effect=lambda callback: callback(screen)):
            spotify.watch()
            return worker, art, lyrics, save

    def test_s_hides_panel_without_entering_fullscreen_and_restores_it(self):
        screen = Screen(['s', 's', 'q'])
        _, art, lyrics, save = self.run_watch(screen)
        self.assertIn('Sözler · [s] Gizle', screen.frames[0])
        self.assertNotIn('Sözler · [s] Gizle', screen.frames[1])
        self.assertIn('Sözler · [s] Gizle', screen.frames[2])
        self.assertTrue(all('Parça' in frame for frame in screen.frames))
        info_edges = [frame.splitlines()[1].index('╮') for frame in screen.frames]
        self.assertEqual(info_edges, [info_edges[0]] * 3)
        self.assertEqual(lyrics.return_value.draw.call_count, 2)
        self.assertTrue(art.return_value.draw.call_args.kwargs['background'])
        save.assert_any_call(show_lyrics=False)
        save.assert_any_call(show_lyrics=True)

    def test_tab_search_paging_and_collection_play_use_selected_uri(self):
        album = {'type': 'album', 'name': 'Albüm Sonucu', 'uri': 'spotify:album:test'}
        worker = Mock(results=queue.Queue())
        jobs = []
        def put(job):
            jobs.append(job)
            kind, value = job
            if kind == 'search':
                worker.results.put(('search', {**value, 'items': [None, album][1:], 'next': True}, None, 0))
        worker.jobs.put.side_effect = put
        screen = Screen(['/', '\t', 'A', '\n', ']', '\n', 'q'])
        self.run_watch(screen, worker)
        self.assertEqual(jobs[0], ('search', {'query': 'A', 'type': 'album', 'offset': 0}))
        self.assertEqual(jobs[1][1]['offset'], 10)
        self.assertEqual(jobs[2], ('play', 'spotify:album:test'))
        self.assertTrue(any('Albüm Sonucu' in frame for frame in screen.frames))

    def test_design_switch_keeps_classic_and_islands_and_saves_choice(self):
        screen = Screen(['t', 't', 'q'])
        _, art, _, save = self.run_watch(screen)
        self.assertNotIn('Klasik', screen.frames[0])
        self.assertIn('Klasik', screen.frames[1])
        self.assertNotIn('╭', screen.frames[1])
        self.assertIn('╭', screen.frames[2])
        self.assertTrue(art.return_value.draw.call_args_list[0].kwargs['background'])
        self.assertNotIn('background', art.return_value.draw.call_args_list[1].kwargs)
        save.assert_any_call(design='classic')
        save.assert_any_call(design='islands')

    def test_classic_design_restores_at_startup_and_panels_do_not_overlap(self):
        screen = Screen(['q'])
        _, art, _, _ = self.run_watch(screen, design='classic')
        self.assertIn('Klasik', screen.frames[0])
        self.assertNotIn('background', art.return_value.draw.call_args.kwargs)
        for columns in (40, 76, 90, 120, 180):
            for show_lyrics in (True, False):
                info, cover, rect = classic_geometry(columns, 30, True, show_lyrics)
                if cover:
                    top, left, width, height = cover
                    self.assertGreaterEqual(left, info)
                    self.assertGreater(width, 0)
                    self.assertLessEqual(left + width, rect[1] if rect else columns)

    def test_square_background_fits_tall_and_wide_terminals_without_cropping(self):
        art = AlbumArt()
        art.image = Image.new('RGB', (96, 96), 'white')
        try:
            for width, height in ((119, 26), (39, 50), (79, 20), (200, 60)):
                screen = Mock()
                art.draw(screen, 1, 2, width, height, 'ASCII', background=True)
                calls = screen.addstr.call_args_list
                min_row = min(c.args[0] for c in calls)
                max_row = max(c.args[0] for c in calls)
                min_col = min(c.args[1] for c in calls)
                end_col = max(c.args[1] + len(c.args[2]) for c in calls)
                side = min(width // 2, height)
                self.assertEqual(end_col - min_col, side * 2)
                self.assertEqual(max_row - min_row + 1, side)
                self.assertGreaterEqual(min_row, 1)
                self.assertLess(max_row, 1 + height)
                self.assertGreaterEqual(min_col, 2)
                self.assertLessEqual(end_col, 2 + width)
        finally:
            art.close()
            art.thread.join(timeout=2)

    def test_lyrics_visibility_setting_is_validated_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(watch_settings, 'SETTINGS_PATH', Path(directory) / 'preferences.json'):
            watch_settings.save_settings(show_lyrics=False, design="classic")
            watch_settings.save_settings(volume=30)
            self.assertIs(watch_settings.load_settings()['show_lyrics'], False)
            self.assertEqual(watch_settings.load_settings()['design'], 'classic')
            watch_settings.save_settings(show_lyrics='wrong', design='wrong')
            self.assertNotIn('design', watch_settings.load_settings())
            self.assertNotIn('show_lyrics', watch_settings.load_settings())


if __name__ == '__main__':
    unittest.main()
