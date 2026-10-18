"""Isolated Icecast listener: AAC HLS plus optional, ordered R2 publication."""
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid

LOG = logging.getLogger('alce-hls')
SEGMENT = re.compile(r'[a-f0-9]{32}-[0-9]+\.ts\Z')


def command(source, output, session):
    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-rw_timeout', '15000000', '-i', source, '-map', '0:a:0', '-vn',
            '-map_metadata', '-1', '-c:a', 'aac', '-profile:a', 'aac_low',
            '-b:a', '128k', '-ar', '44100', '-ac', '2', '-threads', '1',
            '-f', 'hls', '-hls_time', '10', '-hls_list_size', '6',
            '-hls_start_number_source', 'epoch_us',
            '-hls_flags', 'temp_file+program_date_time+discont_start',
            '-hls_segment_filename', str(output / (session + '-%d.ts')),
            str(output / 'live.m3u8')]


def segments(playlist):
    if not playlist.startswith('#EXTM3U\n'):
        raise ValueError('Invalid playlist')
    names = [line for line in playlist.splitlines() if line and not line.startswith('#')]
    if not names or any(not SEGMENT.fullmatch(name) for name in names):
        raise ValueError('Unsafe or empty segment list')
    return names


class Publisher:
    def __init__(self, client, bucket, prefix):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', prefix):
            raise ValueError('Invalid dedicated HLS prefix')
        self.client, self.bucket, self.prefix = client, bucket, prefix
        self.sent = set()
        self.last = None

    def publish(self, directory):
        path = directory / 'live.m3u8'
        if time.time() - path.stat().st_mtime > 35:
            raise ValueError('Stale encoder output')
        snapshot = path.read_text()
        names = segments(snapshot)
        if snapshot == self.last:
            return False
        # A playlist can never reference an object whose upload has not succeeded.
        for name in names:
            if name not in self.sent:
                self.client.put_object(Bucket=self.bucket, Key=f'{self.prefix}/{name}',
                    Body=(directory / name).read_bytes(), ContentType='video/mp2t',
                    CacheControl='public, max-age=86400, immutable')
                self.sent.add(name)
        self.client.put_object(Bucket=self.bucket, Key=f'{self.prefix}/live.m3u8',
            Body=snapshot.encode(), ContentType='application/vnd.apple.mpegurl',
            CacheControl='public, max-age=2, must-revalidate')
        self.last = snapshot
        self.sent.intersection_update(names)  # bounded memory; old objects expire via R2 lifecycle
        (directory / 'published').touch()
        return True


def clean(directory):
    # Keep ten minutes for readers of previous manifests; never touch other radio data.
    for path in directory.iterdir():
        if (SEGMENT.fullmatch(path.name) or path.name.endswith('.tmp')) and time.time() - path.stat().st_mtime > 600:
            path.unlink(missing_ok=True)


def make_publisher():
    import boto3
    from botocore.config import Config
    endpoint = os.environ['R2_ENDPOINT']
    if not re.fullmatch(r'https://[a-f0-9]+\.r2\.cloudflarestorage\.com', endpoint):
        raise ValueError('Expected official R2 endpoint')
    client = boto3.client('s3', endpoint_url=endpoint, region_name='auto',
        config=Config(connect_timeout=5, read_timeout=10,
                      retries={'mode': 'standard', 'total_max_attempts': 3},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))
    return Publisher(client, os.environ['R2_BUCKET'], os.environ.get('R2_PREFIX', 'alce-test'))


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    directory = Path('/output')
    directory.mkdir(exist_ok=True)
    publisher = make_publisher() if os.environ.get('R2_ENABLED') == 'true' else None
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    def maintenance():
        failing = False
        while not stop.is_set():
            try:
                clean(directory)
                if publisher:
                    publisher.publish(directory)
                if failing:
                    LOG.info('HLS publication recovered')
                failing = False
            except Exception as error:
                # Do not log SDK messages, URLs, headers or credentials.
                if not failing:
                    LOG.warning('HLS publication pending (%s)', type(error).__name__)
                failing = True
            stop.wait(5 if failing else 1)

    worker = threading.Thread(target=maintenance, daemon=True)
    worker.start()
    backoff = 1
    while not stop.is_set():
        started = time.monotonic()
        process = subprocess.Popen(command(os.environ['SOURCE_URL'], directory, uuid.uuid4().hex),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        LOG.info('HLS listener started; production encoder untouched')
        while process.poll() is None and not stop.wait(1):
            pass
        if stop.is_set():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            break
        if time.monotonic() - started > 60:
            backoff = 1
        LOG.warning('HLS source disconnected; retry in %ss', backoff)
        stop.wait(backoff)
        backoff = min(30, backoff * 2)
    worker.join(timeout=2)


if __name__ == '__main__':
    main()
