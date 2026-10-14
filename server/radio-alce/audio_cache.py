"""Bounded on-demand media cache; a ready path means downloaded and probed audio."""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
import config
from catalogs import valid_url


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                             '-of', 'json', str(path)], capture_output=True, timeout=20, check=True)
    data = json.loads(result.stdout)
    if not any(stream.get('codec_type') == 'audio' for stream in data.get('streams', [])):
        raise ValueError('No audio')
    duration = float(data['format']['duration'])
    if duration <= 0:
        raise ValueError('Invalid duration')
    return duration


def trailing_silence_cue(path, duration, window=12., threshold_db=-60, minimum=0.35):
    """Return a safe cue-out at the start of true trailing silence, or None."""
    if duration <= minimum:
        return None
    start = max(0., duration - window)
    length = max(0.1, duration - start)
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-v', 'info',
        '-ss', str(start), '-i', str(path), '-t', str(length),
        '-af', f'silencedetect=noise={threshold_db}dB:d={minimum}',
        '-f', 'null', '-'
    ], capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        return None
    starts = [float(value) for value in re.findall(r'silence_start:\s*([\d.]+)', result.stderr)]
    ends = [float(value) for value in re.findall(r'silence_end:\s*([\d.]+)', result.stderr)]
    if not starts or not ends:
        return None
    silence_start, silence_end = starts[-1], ends[-1]
    # Input seeking makes silencedetect timestamps local to this short tail window.
    if abs(silence_end - length) > 0.20:
        return None
    cue = start + silence_start
    if duration - cue < minimum or cue < 5.:
        return None
    return round(cue, 3)


class AudioCache:
    def __init__(self, directory, limit=config.CACHE_BYTES, download=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o755)
        self.limit = limit
        self.download = download or self._download
        self.lock = threading.RLock()
        self.pinned = set()
        self.analysis = {}

    def pin(self, urls):
        self.pinned = {str(self.directory / (hashlib.sha256(url.encode()).hexdigest() + '.mp3'))
                       for url in urls}

    def _download(self, url, target):
        if not valid_url(url):
            raise ValueError('Invalid audio URL')
        from news import official, OfficialRedirects
        opener = urllib.request.build_opener(OfficialRedirects()) if official(url) else urllib.request.build_opener()
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'RadioAlceServer/2.0'}),
                         timeout=30) as response, target.open('wb') as handle:
            if not valid_url(response.url):
                raise ValueError('Invalid audio redirect')
            size = 0
            while data := response.read(64 * 1024):
                size += len(data)
                if size > config.MAX_AUDIO_BYTES:
                    raise ValueError('Audio too large')
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def prepare(self, item):
        # One worker owns writes; lock also makes FreeTTS/news prefetch validation race-safe.
        with self.lock:
            digest = hashlib.sha256(item['url'].encode()).hexdigest()
            path = self.directory / (digest + '.mp3')
            tmp = path.with_suffix('.part')
            try:
                if path.exists():
                    try:
                        probe(path)
                    except Exception:
                        path.unlink(missing_ok=True)
                if not path.exists():
                    self.download(item['url'], tmp)
                    duration = probe(tmp)
                    # Decode once before airing, so corrupt frames cannot strand a short block.
                    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(tmp),
                                    '-map', '0:a:0', '-f', 'null', '-'],
                                   capture_output=True, timeout=60, check=True)
                    tmp.chmod(0o644)
                    tmp.replace(path)
                else:
                    duration = probe(path)
                path.chmod(0o644)
                path.touch()
                key = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
                if key not in self.analysis:
                    self.analysis.clear()
                    self.analysis[key] = trailing_silence_cue(path, duration) if item.get('type') == 'MUSIC' else None
                cue_out = self.analysis[key]
                result = dict(item, path=str(path), duration=duration)
                if cue_out is not None:
                    result['media_duration'] = duration
                    result['cue_out'] = cue_out
                    result['duration'] = cue_out
                return result
            finally:
                tmp.unlink(missing_ok=True)

    def prune(self, protected=()):
        protected = set(protected) | self.pinned
        with self.lock:
            files = list(self.directory.glob('*.mp3'))
            total = sum(path.stat().st_size for path in files)
            for path in sorted(files, key=lambda p: p.stat().st_mtime):
                if total <= self.limit:
                    break
                if str(path) not in protected:
                    size = path.stat().st_size
                    path.unlink(missing_ok=True)
                    total -= size
            return total
