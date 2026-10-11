"""Measure decoded signal, not HTTP/metadata availability."""
import re
import subprocess


def volume_detect(path, start_seconds=0):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-ss', str(start_seconds), '-i', str(path),
                             '-af', 'volumedetect', '-f', 'null', '-'],
                            check=True, capture_output=True, text=True)
    levels = {}
    for key in ('mean_volume', 'max_volume'):
        match = re.search(rf'{key}:\s*(-?inf|[-\d.]+) dB', result.stderr)
        if match is None:
            raise AssertionError(f'FFmpeg did not report {key}')
        levels[key] = float(match.group(1))
    return levels


def require_audible(levels):
    assert levels['mean_volume'] > -40, f'Inaudible output: {levels}'
    assert levels['max_volume'] > -20, f'Inaudible output: {levels}'
