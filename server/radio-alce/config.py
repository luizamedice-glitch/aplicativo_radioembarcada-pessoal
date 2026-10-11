"""Station-wide settings. No credentials; FreeTTS key is read only by its adapter."""
import os
from pathlib import Path

BASE = 'https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev'
CATALOG_URL = os.getenv('MUSIC_CATALOG_URL', BASE + '/music_catalog.json')
PROGRAMMING_URL = os.getenv('PROGRAMMING_URL', BASE + '/programming.json')
RSS_URL = 'https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml'
NEWS_INTRO_URL = BASE + '/Vinheta_Noticias_Masterizada.mp3'
DATA = Path(os.getenv('RADIO_DATA_DIR', '/data'))
REPEAT_WINDOWS = (6 * 3600, 3 * 3600, 90 * 60, 0)
ARTIST_WINDOW = 90 * 60
HISTORY_RETENTION = 48 * 3600
HISTORY_LIMIT = 500
INSERTION_PATTERN = ('STATION_ID', 'STATION_ID', 'JINGLE')
NEWS_INTERVAL = 30 * 60
NEWS_MAX_AGE = 24 * 3600
NEWS_MIN_DURATION = 30
NEWS_MAX_DURATION = 240
NEWS_REFRESH = 15 * 60
NEWS_HISTORY_LIMIT = 100
SYNC_INTERVAL = 60
FAILURE_COOLDOWN = 10 * 60
CACHE_BYTES = int(os.getenv('RADIO_CACHE_BYTES', str(512 * 1024 ** 2)))
MAX_AUDIO_BYTES = 150 * 1024 ** 2
PREPARED_ITEMS = 6
MUSIC_FADE_SECONDS = 15.
GAINS = {'MUSIC': .9, 'STATION_ID': .8, 'JINGLE': .8, 'NEWS_INTRO': .8,
         'NEWS_DROP': .9, 'TIME_ANNOUNCEMENT': .8}
TIME_ZONE = 'America/Sao_Paulo'
# Do not claim HH:30 when the safe boundary is HH:34. Music is never interrupted.
TIME_MAX_LATENESS = 60
