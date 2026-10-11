import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news import RemoteNewsProvider, parse_rss, resolve_audio, official, OfficialRedirects
from time_announcements import TimeAnnouncements, FreeTtsProvider, text_for
from audio_cache import AudioCache
from storage import Storage
import config

RSS = b'''<rss><channel>
<item><guid>new</guid><title>Nova noticia</title><link>https://agenciabrasil.ebc.com.br/radioagencia-nacional/nova</link>
<pubDate>Sun, 11 Oct 2026 12:00:00 GMT</pubDate><enclosure url="https://agenciabrasil.ebc.com.br/audio/new.mp3" type="audio/mpeg"/><duration>01:00</duration><category>Geral</category></item>
<item><guid>old</guid><title>Outra noticia</title><link>https://agenciabrasil.ebc.com.br/radioagencia-nacional/outra</link>
<pubDate>Sun, 11 Oct 2026 11:00:00 GMT</pubDate></item>
<item><guid>bad</guid><title>Invalida</title><link>https://external.example/news</link><pubDate>Sun, 11 Oct 2026 12:00:00 GMT</pubDate></item>
</channel></rss>'''
NOW = datetime(2026, 10, 11, 12, 30, tzinfo=ZoneInfo('UTC')).timestamp()

class NewsTests(unittest.TestCase):
    def provider(self):
        provider = RemoteNewsProvider(clock=lambda: NOW, fetch=Mock(return_value=RSS))
        provider.refresh()
        return provider

    def test_rss_fixture_metadata_sorted_official_enclosure(self):
        items = parse_rss(RSS)
        self.assertEqual(['new', 'old'], [i['id'] for i in items])
        self.assertEqual(60, items[0]['duration'])
        self.assertEqual('Radioagência Nacional', items[0]['source'])
        self.assertEqual('Geral', items[0]['category'])

    def test_html_resolution_rejects_external_audio_accepts_official(self):
        page = '<source src="https://evil.example/a.mp3"><a href="/audio/real.mp3">Baixar</a>'
        self.assertEqual('https://agenciabrasil.ebc.com.br/audio/real.mp3',
                         resolve_audio('https://agenciabrasil.ebc.com.br/news', page))
        self.assertFalse(official('https://ebc.com.br.evil.example/a.mp3', audio=True))
        self.assertFalse(official('http://agenciabrasil.ebc.com.br/a.mp3', audio=True))
        with self.assertRaises(ValueError):
            OfficialRedirects().redirect_request(None, None, 302, '', {}, 'https://evil.example/a')

    def test_latest_unplayed_chosen_and_no_audio_skipped(self):
        provider = self.provider()
        prepare = lambda item: dict(item, path='/cache/test.mp3', duration=60)
        self.assertEqual('new', provider.candidate(set(), prepare)['id'])
        provider.fetch.return_value = b'<source src="/audio/other.mp3">'
        self.assertEqual('old', provider.candidate({'new'}, prepare)['id'])
        provider.fetch.return_value = b'<p>No audio</p>'
        self.assertIsNone(provider.candidate({'new'}, prepare))

    def test_feed_failure_retains_items_and_never_raises(self):
        provider = self.provider()
        provider.refreshed = 0
        provider.fetch.side_effect = OSError('offline')
        provider.refresh()
        self.assertEqual(2, len(provider.items))

    def test_age_duration_and_history_filter(self):
        provider = self.provider()
        provider.items[0]['duration'] = 800
        provider.items[1]['publishedAt'] = NOW - 90000
        self.assertEqual([], provider.eligible(set()))

    def test_news_history_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.sqlite3'
            db = Storage(path)
            db.started({'id':'new','type':'NEWS_DROP','title':'News'}, {}, NOW, 172800, 500, 100)
            db.close()
            restored = Storage(path)
            self.assertEqual({'new'}, restored.played_news())
            self.assertEqual(NOW, restored.get('last_news_played_at'))
            self.assertEqual({}, restored.history())
            restored.close()

class TimeTests(unittest.TestCase):
    def test_portuguese_hour_phrases(self):
        self.assertEqual('Agora são oito horas.', text_for(8, 0))
        self.assertEqual('Agora são vinte e três horas e trinta minutos.', text_for(23, 30))
        self.assertEqual('Agora é uma hora.', text_for(1, 0))
        self.assertEqual('Agora é meia-noite.', text_for(0, 0))

    @patch('time_announcements.probe', return_value=3)
    def test_sao_paulo_cache_and_conflict_omits_only_hour(self, probe):
        with tempfile.TemporaryDirectory() as root:
            provider = Mock()
            times = TimeAnnouncements(root, provider)
            boundary = datetime(2026,10,11,10,30,30,tzinfo=ZoneInfo('America/Sao_Paulo')).timestamp()
            item = times.ready(boundary)
            self.assertEqual('time-20261011-1030', item['id'])
            self.assertEqual('1030.mp3', Path(item['path']).name)
            self.assertIsNone(times.ready(boundary + 31))
            provider.generate.assert_not_called()

    @patch('time_announcements.probe', return_value=3)
    def test_48_files_persist_and_do_not_regenerate(self, probe):
        with tempfile.TemporaryDirectory() as root:
            probe.side_effect = lambda path: 3 if Path(path).exists() else (_ for _ in ()).throw(FileNotFoundError())
            provider = Mock()
            provider.generate.side_effect = lambda text, path: path.write_bytes(b'fixture')
            stop = Mock(); stop.wait.return_value = False
            times = TimeAnnouncements(root, provider)
            times.warm_all(stop)
            self.assertEqual(48, len(list(Path(root).glob('*.mp3'))))
            self.assertEqual(48, provider.generate.call_count)
            TimeAnnouncements(root, provider).warm_all(stop)
            self.assertEqual(48, provider.generate.call_count)

    def test_missing_hour_skipped_without_tts_on_air(self):
        with tempfile.TemporaryDirectory() as root:
            provider = Mock()
            times = TimeAnnouncements(root, provider)
            boundary = datetime(2026,10,11,10,0,0,tzinfo=ZoneInfo('America/Sao_Paulo')).timestamp()
            self.assertIsNone(times.ready(boundary))
            provider.generate.assert_not_called()

    def test_freetts_request_contract_and_download(self):
        with tempfile.TemporaryDirectory() as root:
            provider = FreeTtsProvider(api_key='fixture-only')
            response = Mock(); response.read.return_value = json.dumps({'file_id':'11111111-1111-1111-1111-111111111111'}).encode()
            audio = Mock(); audio.read.return_value = b'fixture-audio'
            first = Mock(); first.__enter__ = Mock(return_value=response); first.__exit__ = Mock(return_value=False)
            second = Mock(); second.__enter__ = Mock(return_value=audio); second.__exit__ = Mock(return_value=False)
            provider.opener = Mock(); provider.opener.open.side_effect = [first, second]
            target = Path(root) / 'hour.part'
            provider.generate('Agora são oito horas.', target)
            request = provider.opener.open.call_args_list[0].args[0]
            self.assertEqual('POST', request.method)
            self.assertEqual('fixture-only', request.get_header('X-api-key'))
            self.assertEqual('pt-BR-AntonioNeural', json.loads(request.data)['voice'])
            self.assertEqual(b'fixture-audio', target.read_bytes())

class CacheTests(unittest.TestCase):
    @patch('audio_cache.probe', return_value=5)
    @patch('audio_cache.subprocess.run')
    def test_verified_cache_reused_and_lru_protects_pending_and_pinned(self, decode, probe):
        with tempfile.TemporaryDirectory() as root:
            download = Mock(side_effect=lambda url, path: path.write_bytes(b'0123456789'))
            cache = AudioCache(root, limit=10, download=download)
            items = [{'id': str(i), 'type':'MUSIC', 'url': f'https://example.org/{i}.mp3'} for i in range(3)]
            paths = [cache.prepare(i)['path'] for i in items]
            cache.prepare(items[0])
            self.assertEqual(3, download.call_count)
            self.assertEqual(3, decode.call_count)
            cache.pin([items[1]['url']])
            cache.prune([paths[2]])
            self.assertFalse(Path(paths[0]).exists())
            self.assertTrue(Path(paths[1]).exists())
            self.assertTrue(Path(paths[2]).exists())

if __name__ == '__main__': unittest.main()
