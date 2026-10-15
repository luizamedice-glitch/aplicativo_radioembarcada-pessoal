"""Measure only near-digital silence at file edges; never modify the source MP3."""
import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger('radio')
POLICY_VERSION = 2
SILENCE_DB = -80
MIN_SILENCE_SECONDS = .25
EDGE_MARGIN_SECONDS = .01
MAX_TRIM_SECONDS = 5.


def measure(path):
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-xerror', '-i', str(path),
        '-map', '0:a:0', '-af', f'silencedetect=noise={SILENCE_DB}dB:d={MIN_SILENCE_SECONDS}',
        '-progress', 'pipe:1', '-f', 'null', '-'], capture_output=True, text=True,
        timeout=120, check=True)
    times = re.findall(r'^out_time_us=(\d+)$', result.stdout, re.M)
    if not times or int(times[-1]) <= 0:
        raise ValueError('Missing decoded audio duration')
    duration = int(times[-1]) / 1_000_000
    intervals = [(float(a), float(b)) for a, b in re.findall(
        r'silence_start: ([\d.]+).*?silence_end: ([\d.]+)', result.stderr, re.S)]
    start, end = 0., duration
    for a, b in intervals:
        if a <= .001 and MIN_SILENCE_SECONDS <= b <= MAX_TRIM_SECONDS:
            start = max(0., b - EDGE_MARGIN_SECONDS)
        if abs(b - duration) <= .03 and MIN_SILENCE_SECONDS <= duration - a <= MAX_TRIM_SECONDS:
            end = min(duration, a + EDGE_MARGIN_SECONDS)
    if end - start < .25:
        start, end = 0., duration
    return {'version': POLICY_VERSION, 'bytes': path.stat().st_size,
            'decoded_duration': duration, 'start': start, 'end': end}


def prepared_boundaries(path, kind):
    """Only MUSIC tail and STATION_ID/JINGLE head are adjusted in this change."""
    if kind not in ('MUSIC', 'STATION_ID', 'JINGLE'):
        return {}
    path = Path(path)
    sidecar = path.with_suffix('.edges.json')
    try:
        data = json.loads(sidecar.read_text())
        if (data['version'] != POLICY_VERSION or data['bytes'] != path.stat().st_size
                or not 0 <= data['start'] < data['end'] <= data['decoded_duration']):
            raise ValueError('Stale analysis')
    except (OSError, ValueError, KeyError, TypeError):
        data = measure(path)
        tmp = sidecar.with_suffix('.tmp')
        tmp.write_text(json.dumps(data))
        tmp.replace(sidecar)
    start = data['start'] if kind in ('STATION_ID', 'JINGLE') else 0.
    end = data['end'] if kind == 'MUSIC' else data['decoded_duration']
    log.info('AUDIO edges type=%s head=%.3fs tail=%.3fs duration=%.3fs',
             kind, start, data['decoded_duration'] - end, end - start)
    return {'cue_in': start, 'cue_out': end, 'duration': end - start}
