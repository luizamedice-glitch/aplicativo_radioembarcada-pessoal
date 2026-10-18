"""Station-wide settings. No credentials; FreeTTS key is read only by its adapter."""
import os
from pathlib import Path

BASE = 'https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev'
CATALOG_URL = os.getenv('MUSIC_CATALOG_URL', BASE + '/music_catalog.json')
PROGRAMMING_URL = os.getenv('PROGRAMMING_URL', BASE + '/programming.json')
DISABLED_PROGRAM_IDS = {value.strip() for value in os.getenv(
    'DISABLED_PROGRAM_IDS', 'jingle-spot-bifao,jingle-spot-salao-flack'
).split(',') if value.strip()}
RSS_URL = 'https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml'
NEWS_INTRO_URL = BASE + '/Vinheta_Noticias_Masterizada.mp3'
DATA = Path(os.getenv('RADIO_DATA_DIR', '/data'))
REPEAT_WINDOWS = (6 * 3600, 3 * 3600, 90 * 60, 0)
ARTIST_WINDOW = 90 * 60
HISTORY_RETENTION = 48 * 3600
HISTORY_LIMIT = 500
# Legacy rollback compatibility only; active scheduling is time-based in ProgrammingEngine.insertion.
INSERTION_PATTERN = ('STATION_ID', 'STATION_ID', 'JINGLE')
JINGLE_INTERVAL = 60 * 60
# Vinhetas editoriais pareadas: ficam fora do sorteio comum e só antecedem a música indicada.
MUSIC_STATION_ID_PAIRS = (
    ("cant stop loving you", "rock internacional"),
    ("tarzan boy", "disco anos 80"),
)
# Bloco especial de músicas italianas. A pasta fica fora de music/, então estas faixas
# nunca entram no sorteio musical normal.
ITALIAN_BLOCK_TIMES = ((16, 10), (19, 10), (22, 10))
ITALIAN_BLOCK_MAX_LATENESS = 60 * 60
ITALIAN_BLOCK_INTRO = {
    'id': 'vinheta-bloco-italianas',
    'type': 'STATION_ID',
    'title': 'Vinheta Bloco Italianas',
    'url': BASE + '/Bloco%20-%20Italianas/Vinheta_Bloco_Italianas_Masterizada.mp3',
}
ITALIAN_BLOCK_TRACKS = (
    {'id': 'italiana-tra-te-e-il-mare', 'type': 'MUSIC', 'title': 'Tra te e il mare',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/1.%20Tra%20te%20e%20il%20mare.mp3'},
    {'id': 'italiana-con-te-partiro', 'type': 'MUSIC', 'title': 'Con Te Partirò',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/2.%20Con%20Te%20Partir%C3%B2.mp3'},
    {'id': 'italiana-per-amore', 'type': 'MUSIC', 'title': 'Per Amore',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/3.%20Per%20Amore.mp3'},
    {'id': 'italiana-la-solitudine', 'type': 'MUSIC', 'title': 'La solitudine',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/4.%20La%20solitudine.mp3'},
    {'id': 'italiana-un-gatto-nel-blu', 'type': 'MUSIC', 'title': 'Un Gatto Nel Blu — Versão Remasterizada',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/6.%20Un%20Gatto%20Nel%20Blu%20-%20Vers%C3%A3o%20Remasterizada.mp3'},
    {'id': 'italiana-tornero', 'type': 'MUSIC', 'title': "Tornero'",
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/7.%20Tornero%27.mp3'},
    {'id': 'italiana-la-dolce-vita', 'type': 'MUSIC', 'title': 'La Dolce Vita',
     'artist': '', 'url': BASE + '/Bloco%20-%20Italianas/8.%20La%20Dolce%20Vita.mp3'},
)
NEWS_INTERVAL = 4 * 60 * 60
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
MUSIC_END_TRIM_SECONDS = 20.
MUSIC_FADE_SECONDS = 15.
MUSIC_FADE_FLOOR = .03  # Never latch the music at zero before its boundary.
GAINS = {'MUSIC': .9, 'STATION_ID': .8, 'JINGLE': .8, 'NEWS_INTRO': .8,
         'NEWS_DROP': .9, 'TIME_ANNOUNCEMENT': .8}
TIME_ZONE = 'America/Sao_Paulo'
# Do not claim HH:30 when the safe boundary is HH:34. Music is never interrupted.
TIME_MAX_LATENESS = 60
