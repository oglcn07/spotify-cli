"""Offline checks for lyric timing, worker isolation, and responsive panels."""

import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from watch_lyrics import Lyrics, active_line, fetch_lyrics, fetch_fallback, panel_layout, parse_lrc


class LyricsTests(unittest.TestCase):
    def test_multiple_stamps_offset_and_seek(self):
        lines = parse_lrc('[offset:-500]\n[ar:Artist]\n[00:02.50][01:03.125] Nakarat\n[00:01] İlk\n[00:04.00]')
        self.assertEqual(lines, [(0.5, 'İlk'), (2.0, 'Nakarat'), (3.5, ''), (62.625, 'Nakarat')])
        self.assertEqual(active_line(lines, 0), -1)
        self.assertEqual(active_line(lines, 2), 1)
        self.assertEqual(active_line(lines, 64), 3)
        self.assertEqual(active_line(lines, 1), 0)

    def test_layout_stays_within_terminal_and_panels_do_not_overlap(self):
        for columns in (20, 80, 90, 119, 120, 180, 260):
            for artwork in (False, True):
                info, cover_left, cover_width, lyric_left, lyric_width = panel_layout(columns, 30, artwork)
                if cover_width:
                    self.assertLess(info, cover_left)
                    self.assertLessEqual(cover_left + cover_width, columns - 1)
                if lyric_width:
                    self.assertLess(info, lyric_left)
                    self.assertLessEqual(cover_left + cover_width, lyric_left)
                    self.assertLessEqual(lyric_left + lyric_width, columns - 1)
        self.assertEqual(panel_layout(80, 24, focused=True)[3:], (1, 78))
        self.assertEqual(panel_layout(180, 10)[2:], (0, 0, 0))

    def test_fetch_encodes_metadata_and_reads_plain_lyrics(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'plainLyrics': 'Bir\nİki'}).encode()
        with patch('watch_lyrics.urllib.request.urlopen', return_value=response) as request:
            synced, plain, _ = fetch_lyrics(('Şarkı & Ben', 'Sanatçı', 'Albüm', 123))
        self.assertEqual(synced, [])
        self.assertEqual(plain, ['Bir', 'İki'])
        self.assertIn('duration=123', request.call_args.args[0].full_url)
        self.assertIn('%26', request.call_args.args[0].full_url)
        self.assertEqual(request.call_args.kwargs['timeout'], 6)

    def test_worker_ignores_stale_result_and_caches_tracks(self):
        state = lambda title: {'title': title, 'artist': 'Artist', 'mpris:length': 120}
        with patch('watch_lyrics.fetch_lyrics', return_value=([(0, 'Satır')], [], '')) as fetch:
            lyrics = Lyrics()
            try:
                lyrics.request(state('A'))
                first = lyrics.results.get(timeout=2)
                lyrics.request(state('B'))
                second = lyrics.results.get(timeout=2)
                lyrics.results.put(first)
                lyrics.poll()
                self.assertEqual(lyrics.synced, [])
                lyrics.results.put(second)
                lyrics.poll()
                lyrics.request(state('A'))
                lyrics.results.get(timeout=2)
                self.assertEqual(fetch.call_count, 2)
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)
            self.assertFalse(lyrics.thread.is_alive())

    def test_rate_limit_blocks_next_track_request(self):
        error = urllib.error.HTTPError('https://lrclib.net', 429, 'limit', {'Retry-After': '120'}, io.BytesIO())
        with patch('watch_lyrics.fetch_lyrics', side_effect=error) as fetch, patch('watch_lyrics.fetch_fallback', side_effect=error):
            lyrics = Lyrics()
            try:
                lyrics.request({'title': 'A', 'artist': 'B'})
                lyrics.results.get(timeout=2)
                lyrics.request({'title': 'C', 'artist': 'B'})
                result = lyrics.results.get(timeout=2)
                self.assertIn('otomatik yeniden denenecek', result[1][2])
                self.assertEqual(fetch.call_count, 1)
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_primary_outage_uses_fallback_and_attributes_source(self):
        error = urllib.error.HTTPError('https://lrclib.net', 502, 'gateway', {}, io.BytesIO())
        with patch('watch_lyrics.fetch_lyrics', side_effect=error) as primary, patch('watch_lyrics.fetch_fallback', return_value=([], ['Yedek söz'], '')) as fallback:
            lyrics = Lyrics()
            try:
                state = {'title': 'A', 'artist': 'B'}
                lyrics.request(state)
                result = lyrics.results.get(timeout=2)
                lyrics.results.put(result)
                lyrics.poll()
                self.assertEqual(lyrics.plain, ['Yedek söz'])
                self.assertEqual(lyrics.source, 'lyrics.ovh')
                lyrics.request({'title': 'C', 'artist': 'B'})
                lyrics.results.get(timeout=2)
                self.assertEqual(primary.call_count, 1)
                self.assertEqual(fallback.call_count, 2)
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_failed_track_retries_automatically_without_cached_error(self):
        with patch('watch_lyrics.fetch_lyrics', side_effect=OSError('offline')), patch('watch_lyrics.fetch_fallback', side_effect=OSError('offline')):
            lyrics = Lyrics()
            try:
                state = {'title': 'A', 'artist': 'B'}
                lyrics.request(state)
                result = lyrics.results.get(timeout=2)
                lyrics.results.put(result)
                lyrics.poll()
                deadline = lyrics.next_retry
                self.assertNotEqual(deadline, float('inf'))
                with patch('watch_lyrics.time.monotonic', return_value=deadline + 1), patch('watch_lyrics.fetch_lyrics', return_value=([(0, 'Recovered')], [], '')) as recovered:
                    lyrics.request(state)
                    result = lyrics.results.get(timeout=2)
                    lyrics.results.put(result)
                    lyrics.poll()
                    self.assertEqual(lyrics.synced, [(0, 'Recovered')])
                    recovered.assert_called_once()
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_plain_fallback_expires_and_upgrades_to_timed_lyrics(self):
        with patch('watch_lyrics.configured_key', return_value=''), patch('watch_lyrics.fetch_lyrics', side_effect=OSError('offline')), patch('watch_lyrics.fetch_fallback', return_value=([], ['Plain line'], '')):
            lyrics = Lyrics()
            try:
                state = {'title': 'Title', 'artist': 'Artist'}
                lyrics.request(state)
                first = lyrics.results.get(timeout=2)
                lyrics.results.put(first)
                lyrics.poll()
                self.assertEqual(lyrics.plain, ['Plain line'])
                deadline = lyrics.next_retry
                self.assertNotEqual(deadline, float('inf'))
                with patch('watch_lyrics.time.monotonic', return_value=deadline + 1), patch('watch_lyrics.fetch_lyrics', return_value=([(1.0, 'Timed line')], [], '')) as recovered:
                    lyrics.request(state)
                    self.assertEqual(lyrics.plain, ['Plain line'])
                    updated = lyrics.results.get(timeout=2)
                    lyrics.results.put(updated)
                    lyrics.poll()
                    self.assertEqual(lyrics.synced, [(1.0, 'Timed line')])
                    self.assertEqual(lyrics.source, 'LRCLIB')
                    recovered.assert_called_once()
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_fallback_encodes_artist_and_title(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'lyrics': ' Satır '}).encode()
        with patch('watch_lyrics.urllib.request.urlopen', return_value=response) as request:
            result = fetch_fallback(('A/B', 'Şarkıcı', '', 120))
        self.assertEqual(result[1], ['Satır'])
        self.assertIn('A%2FB', request.call_args.args[0].full_url)
        self.assertNotIn('Ş', request.call_args.args[0].full_url)

    def test_fallback_tries_lead_artist_only_after_not_found(self):
        missing = urllib.error.HTTPError('https://api.lyrics.ovh', 404, 'missing', {}, io.BytesIO())
        with patch('watch_lyrics.fetch_fallback_record', side_effect=[missing, ([], ['Found'], '')]) as fetch:
            self.assertEqual(fetch_fallback(('Title', 'Lead, Guest', '', 120))[1], ['Found'])
            self.assertEqual(fetch.call_args_list[1].args, ('Title', 'Lead'))
        limited = urllib.error.HTTPError('https://api.lyrics.ovh', 429, 'limit', {}, io.BytesIO())
        with patch('watch_lyrics.fetch_fallback_record', side_effect=limited) as fetch:
            with self.assertRaises(urllib.error.HTTPError):
                fetch_fallback(('Title', 'Lead, Guest', '', 120))
            fetch.assert_called_once()

    def test_cooldown_preserves_original_error_and_fallback_miss(self):
        gateway = urllib.error.HTTPError('https://lrclib.net', 502, 'gateway', {}, io.BytesIO())
        missing = urllib.error.HTTPError('https://api.lyrics.ovh', 404, 'missing', {}, io.BytesIO())
        with patch('watch_lyrics.fetch_lyrics', side_effect=gateway), patch('watch_lyrics.fetch_fallback', side_effect=missing):
            lyrics = Lyrics()
            try:
                state = {'title': 'A', 'artist': 'B'}
                lyrics.request(state)
                lyrics.results.get(timeout=2)
                lyrics.request(state, force=True)
                result = lyrics.results.get(timeout=2)
                self.assertIn('LRCLIB: HTTP 502', result[1][2])
                self.assertIn('lyrics.ovh: söz bulunamadı', result[1][2])
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)

    def test_error_draw_wraps_details_and_shows_retry_countdown(self):
        lyrics = Lyrics()
        try:
            lyrics.message = 'LRCLIB: HTTP 502 · lyrics.ovh: söz bulunamadı; otomatik yeniden denenecek.'
            lyrics.next_retry = 110
            screen = Mock()
            with patch('watch_lyrics.time.monotonic', return_value=100):
                lyrics.draw(screen, 2, 90, 28, 15, 0)
            drawn = ' '.join(call.args[2] for call in screen.addnstr.call_args_list)
            self.assertIn('HTTP 502', drawn)
            self.assertIn('11 sn', drawn)
            self.assertTrue(all(len(call.args[2]) <= 28 or 'Yeniden deneme' in call.args[2] for call in screen.addnstr.call_args_list))
        finally:
            lyrics.close()
            lyrics.thread.join(timeout=2)

    def test_draw_highlights_current_line_and_plain_scroll_is_clamped(self):
        lyrics = Lyrics()
        try:
            lyrics.synced = [(0, 'Bir'), (2, 'İki'), (4, 'Üç')]
            screen = Mock()
            lyrics.draw(screen, 2, 90, 30, 8, 3)
            self.assertTrue(any(call.args[2] == '› İki' for call in screen.addnstr.call_args_list))
            lyrics.synced = []
            lyrics.plain = ['Satır'] * 20
            lyrics.offset = 100
            lyrics.draw(screen, 2, 90, 30, 8, 3)
            self.assertEqual(lyrics.offset, 14)
        finally:
            lyrics.close()
            lyrics.thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
