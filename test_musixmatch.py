"""Offline checks for optional Musixmatch authentication and timed lyrics."""

import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from watch_musixmatch import api_call, fetch_musixmatch, MusixmatchError
from watch_lyrics import Lyrics


class MusixmatchTests(unittest.TestCase):
    def test_timed_match_preserves_copyright_and_duration(self):
        record = {'subtitle': {'subtitle_body': '[00:02.50] Line', 'lyrics_copyright': 'Copyright owner'}}
        with patch('watch_musixmatch.api_call', return_value=record) as call:
            synced, plain, notice = fetch_musixmatch(('Title', 'Artist', 'Album', 240), 'secret')
        self.assertEqual(synced, [(2.5, 'Line')])
        self.assertEqual(plain, [])
        self.assertEqual(notice, 'Copyright owner')
        self.assertEqual(call.call_args.args[1]['f_subtitle_length'], 240)
        self.assertEqual(call.call_args.args[1]['subtitle_format'], 'lrc')

    def test_missing_subtitle_access_can_use_plain_lyrics(self):
        with patch('watch_musixmatch.api_call', side_effect=[MusixmatchError(403), {'lyrics': {'lyrics_body': 'Plain line'}}]):
            self.assertEqual(fetch_musixmatch(('Title', 'Artist', '', 0), 'secret'), ([], ['Plain line'], ''))

    def test_restricted_content_is_not_displayed(self):
        with patch('watch_musixmatch.api_call', return_value={'lyrics': {'restricted': 1, 'lyrics_body': 'Restricted'}}):
            with self.assertRaises(MusixmatchError) as raised:
                fetch_musixmatch(('Title', 'Artist', '', 0), 'secret')
            self.assertEqual(raised.exception.code, 403)

    def test_http_error_never_exposes_secret_url(self):
        error = urllib.error.HTTPError('https://api.musixmatch.com/?apikey=secret', 429, 'limit', {'Retry-After': '90'}, io.BytesIO())
        with patch('watch_musixmatch.urllib.request.urlopen', side_effect=error):
            with self.assertRaises(MusixmatchError) as raised:
                api_call('matcher.subtitle.get', {}, 'secret')
        self.assertNotIn('secret', str(raised.exception))
        self.assertEqual(raised.exception.headers['Retry-After'], '90')

    def test_http_200_with_auth_failure_is_not_success(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'message': {'header': {'status_code': 401}, 'body': []}}).encode()
        with patch('watch_musixmatch.urllib.request.urlopen', return_value=response):
            with self.assertRaises(MusixmatchError) as raised:
                api_call('matcher.subtitle.get', {}, 'secret')
        self.assertEqual(raised.exception.code, 401)

    def test_worker_uses_timed_musixmatch_when_primary_is_offline(self):
        with patch('watch_lyrics.configured_key', return_value='secret'), patch('watch_lyrics.fetch_lyrics', side_effect=OSError('offline')), patch('watch_lyrics.fetch_musixmatch', return_value=([(1.0, 'Line')], [], 'Copyright')), patch('watch_lyrics.fetch_fallback') as fallback:
            lyrics = Lyrics()
            try:
                lyrics.request({'title': 'Title', 'artist': 'Artist'})
                result = lyrics.results.get(timeout=2)
                lyrics.results.put(result)
                lyrics.poll()
                self.assertEqual(lyrics.source, 'Musixmatch')
                self.assertEqual(lyrics.synced, [(1.0, 'Line')])
                fallback.assert_not_called()
            finally:
                lyrics.close()
                lyrics.thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
