"""Pluggable server-only TTS adapter. 48 persistent half-hour files; never wait on air."""
import json
import logging
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo
import config
from audio_cache import probe

log = logging.getLogger('radio')
NUMBERS = ('zero', 'uma', 'duas', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove',
           'dez', 'onze', 'doze', 'treze', 'catorze', 'quinze', 'dezesseis', 'dezessete',
           'dezoito', 'dezenove', 'vinte', 'vinte e uma', 'vinte e duas', 'vinte e três')


def text_for(hour, minute):
    if hour == 0 and minute == 0:
        return 'Agora é meia-noite.'
    if hour == 0:
        return 'Agora é meia-noite e trinta minutos.'
    start = f'Agora é {NUMBERS[hour]} hora' if hour == 1 else f'Agora são {NUMBERS[hour]} horas'
    return start + (' e trinta minutos.' if minute else '.')


class TtsProvider(Protocol):
    def generate(self, text: str, target: Path): ...


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('TTS redirect rejected')


class FreeTtsProvider:
    def __init__(self, api_key=None):
        self.api_key = os.getenv('FREETTS_API_KEY', '') if api_key is None else api_key
        self.voice = os.getenv('FREETTS_VOICE', 'pt-BR-AntonioNeural')
        self.opener = urllib.request.build_opener(NoRedirects())

    def generate(self, text, target):
        if not self.api_key or self.api_key == 'coloque-sua-chave-aqui':
            raise ValueError('TTS not configured')
        body = json.dumps({'text': text, 'voice': self.voice, 'rate': '+5%', 'pitch': '+0Hz',
                           'output_format': 'mp3'}).encode()
        request = urllib.request.Request('https://freetts.org/api/v1/tts', data=body,
            headers={'Content-Type': 'application/json', 'x-api-key': self.api_key}, method='POST')
        with self.opener.open(request, timeout=30) as response:
            file_id = json.loads(response.read(64 * 1024))['file_id']
        if not isinstance(file_id, str) or not re.fullmatch(r'[a-fA-F0-9-]{36}', file_id):
            raise ValueError('Invalid TTS file id')
        with self.opener.open('https://freetts.org/api/audio/' + file_id, timeout=30) as response:
            data = response.read(5 * 1024 ** 2 + 1)
            if not data or len(data) > 5 * 1024 ** 2:
                raise ValueError('Invalid TTS size')
            with target.open('wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())


class TimeAnnouncements:
    def __init__(self, directory, provider=None, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o755)
        self.provider = provider or FreeTtsProvider()
        self.clock = clock

    def warm_one(self, hour, minute):
        path = self.directory / f'{hour:02}{minute:02}.mp3'
        if path.exists():
            try:
                probe(path)
                path.chmod(0o644)
                return path
            except Exception:
                path.unlink(missing_ok=True)
        tmp = path.with_suffix('.part')
        try:
            self.provider.generate(text_for(hour, minute), tmp)
            probe(tmp)
            tmp.chmod(0o644)
            tmp.replace(path)
            log.info('TIME cached %02d:%02d', hour, minute)
            return path
        finally:
            tmp.unlink(missing_ok=True)

    def warm_all(self, stop):
        if isinstance(self.provider, FreeTtsProvider) and not self.provider.api_key:
            log.warning('TIME FreeTTS not configured; news continues without announcement')
            return
        # At most 8 requests/minute, below the documented free-tier limit of 10.
        local = datetime.fromtimestamp(self.clock(), ZoneInfo(config.TIME_ZONE))
        current = local.hour * 2 + local.minute // 30
        slots = [(index // 2, (index % 2) * 30) for index in range(48)]
        # Make the current/next slot available first on a new installation.
        for hour, minute in slots[current:] + slots[:current]:
            path = self.directory / f'{hour:02}{minute:02}.mp3'
            try:
                probe(path)
                valid = True
            except Exception:
                valid = False
            try:
                self.warm_one(hour, minute)
            except Exception as error:
                log.warning('TIME generation unavailable (%s); will retry later', type(error).__name__)
                return
            if not valid and stop.wait(8):
                return

    def ready(self, boundary):
        local = datetime.fromtimestamp(boundary, ZoneInfo(config.TIME_ZONE))
        slot = local.replace(minute=(local.minute // 30) * 30, second=0, microsecond=0)
        if (local - slot).total_seconds() > config.TIME_MAX_LATENESS:
            log.info('TIME omitted: safe boundary later than 60s; never announce stale time')
            return None
        path = self.directory / f'{slot.hour:02}{slot.minute:02}.mp3'
        try:
            length = probe(path)
            return {'id': 'time-' + slot.strftime('%Y%m%d-%H%M'), 'type': 'TIME_ANNOUNCEMENT',
                    'title': 'Hora certa — Rádio Alce', 'path': str(path), 'duration': length,
                    'slot': slot.timestamp()}
        except Exception:
            log.info('TIME cached announcement missing; skip only time')
            return None
