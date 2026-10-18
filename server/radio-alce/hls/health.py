import os
from pathlib import Path
import time
from pipeline import segments

root = Path('/output')
playlist = root / 'live.m3u8'
assert time.time() - playlist.stat().st_mtime < 35
assert all((root / name).stat().st_size > 0 for name in segments(playlist.read_text()))
if os.environ.get('R2_ENABLED') == 'true':
    assert time.time() - (root / 'published').stat().st_mtime < 45
