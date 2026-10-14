#!/usr/bin/env python3
"""Optional offline Docker integration: real decoders, Icecast and two listeners.
Requires the catalog image: docker build -t alce-catalog-validation -f
server/radio-alce/Dockerfile.catalog server/radio-alce
Run from any directory: python3 server/radio-alce/tests/validate_runtime.py
Only generated tones are used; never touches the deployed stream or musical library.
"""
import concurrent.futures
import sys
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
import threading
import array
import math
from audio_amplitude import volume_detect, require_audible

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'savonet/liquidsoap:v2.4.x-latest@sha256:f19e1ca92320459d5fad5265e0844cc7ae92501d686f788e43ca8a9d6bec44cc'
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']

def docker(*args, **kwargs):
    return subprocess.run(DOCKER + list(args), check=True, capture_output=True, text=True, **kwargs).stdout.strip()

RUNTIME = '''import sys, time, threading, json, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, '/app')
from storage import Storage
from programming import ProgrammingEngine
from sync_catalog import Planner
from audio_cache import probe
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
items = json.loads(Path('/data/fixtures.json').read_text())
class Cache:
 directory = Path('/data/cache')
 def prepare(self, item):
  path=item.get('path', '/data/cache/'+{'NEWS_INTRO':'station', 'NEWS_DROP':'news'}.get(item['type'],'music')+'.mp3')
  return dict(item, path=path, duration=probe(path))
 def prune(self, paths): pass
news_item={'id':'news-fixture','type':'NEWS_DROP','title':'Radioagência Nacional fixture','url':'https://fixture.invalid/news.mp3','path':'/data/cache/news.mp3'}
news = SimpleNamespace(candidate=lambda played, prepare: prepare(news_item) if os.getenv('ALCE_TEST_NEWS')=='1' and news_item['id'] not in played else None)
times = SimpleNamespace(ready=lambda *args: None)
catalogs = SimpleNamespace(music={'items':items['music']}, programming=items['programming'])
planner = Planner(catalogs, ProgrammingEngine(Storage('/data/station.sqlite3')), Cache(), news, times)
if os.getenv('ALCE_TEST_NEWS')=='1':
 planner.engine.state['last_news_slot']=int(time.time()//1800)-1
 planner.engine.storage.put('programming',planner.engine.checkpoint())
def fill():
 while True:
  planner.fill_once()
  time.sleep(.02)
threading.Thread(target=fill, daemon=True).start()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def reply(self,body):
  self.send_response(200); self.end_headers(); self.wfile.write(body.encode())
 def do_GET(self):
  if self.path=='/next':
   if Path('/data/planner-unavailable').exists():
    self.send_response(503); self.end_headers()
   else: self.reply(planner.next())
  elif self.path=='/events': self.reply(Path('/data/events.jsonl').read_text() if Path('/data/events.jsonl').exists() else '')
  else: self.reply('ok')
 def do_POST(self):
  parsed=urlparse(self.path)
  if parsed.path=='/reset':
   with planner.lock: planner.reset_requested=True
  elif parsed.path=='/played':
   query=parse_qs(parsed.query); token=query['token'][0]; item_id=query.get('id',[''])[0]
   with planner.lock:
    delivery=planner.delivered.get(token)
    if delivery:
     with Path('/data/events.jsonl').open('a') as f: f.write(json.dumps({'id':item_id,'type':delivery['item']['type'],'time':time.time(),'duration':delivery['item']['duration']})+'\\n')
   planner.started(token,item_id)
  self.reply('ok')
ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
'''

def main():
    tag = 'alce-validation-' + uuid.uuid4().hex[:8]
    containers = []
    with tempfile.TemporaryDirectory(prefix='alce-runtime-') as directory:
        root = Path(directory); root.chmod(0o755)
        data = root / 'data'; data.mkdir(mode=0o777); data.chmod(0o777)
        cache = data / 'cache'; cache.mkdir(mode=0o755); cache.chmod(0o755)
        for name, length, frequency in [('music',4,440),('station',1.1,880),('jingle',1.3,1320),('news',30,1100)]:
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={frequency}:duration={length}',
                            '-af','volume=2','-c:a','libmp3lame','-b:a','128k',str(cache / (name+'.mp3'))], check=True)
            (cache / (name+'.mp3')).chmod(0o644)
        def item(name, kind, number):
            return {'id':f'{name}-{number}', 'type':kind, 'title':name,
                    'url':f'https://fixture.invalid/{name}/{number}.mp3','path':f'/data/cache/{name}.mp3'}
        fixtures = {'music':[item('music','MUSIC',i) for i in range(20)],
                    'programming': {'version':1,'stationIds':[item('station','STATION_ID',i) for i in range(8)],
                                   'jingles':[item('jingle','JINGLE',i) for i in range(3)]}}
        (data / 'fixtures.json').write_text(json.dumps(fixtures)); (data / 'fixtures.json').chmod(0o644)
        (root / 'runtime.py').write_text(RUNTIME); (root / 'runtime.py').chmod(0o644)
        icecast = root / 'icecast'; icecast.mkdir(mode=0o755)
        shutil.copy(ROOT / 'icecast/Dockerfile', icecast / 'Dockerfile')
        xml = (ROOT / 'icecast/icecast.xml.template').read_text().replace('SOURCE_PASS_PLACEHOLDER','fixture-source').replace('ADMIN_PASS_PLACEHOLDER','fixture-admin')
        (icecast / 'icecast.xml').write_text(xml)
        # Diagnostic stages use the SAME production source/callback/output chain.
        stage=os.getenv('ALCE_AUDIO_STAGE','production')
        processing={
            'production':'',
            'amplify':'program = amplify(override="liq_gain", 0.9, program)\n',
            'fade_out':'program = amplify(override="liq_gain", 0.9, program)\nprogram = fade.out(duration=0., type="sin", program)\n',
            'fade_in':'program = amplify(override="liq_gain", 0.9, program)\nprogram = fade.in(duration=0., type="sin", program)\n',
            'legacy_fades':'program = amplify(override="liq_gain", 0.9, program)\nprogram = fade.out(duration=0., type="sin", program)\nprogram = fade.in(duration=0., type="sin", program)\n',
            'explicit_fades':'program = amplify(override="liq_gain", 0.9, program)\nprogram = fade.out(duration=0., override_duration="liq_fade_out", track_sensitive=true, type="sin", program)\nprogram = fade.in(duration=0., override_duration="liq_fade_in", track_sensitive=true, type="sin", program)\n',
        }
        script=root/'radio.liq'
        original=(ROOT/'liquidsoap/radio.liq').read_text()
        script.write_text(original.replace('radio = fallback(track_sensitive=true, [program, emergency])',
                                          processing[stage]+'radio = fallback(track_sensitive=true, [program, emergency])'))
        script.chmod(0o644)
        docker('build','-t',tag+'-icecast',str(icecast))
        docker('network','create',tag)
        try:
            for name, args in [
                ('icecast',['--network-alias','icecast','-p','127.0.0.1::8000',tag+'-icecast']),
                ('catalog',['--network-alias','catalog','-p','127.0.0.1::8081','-v',f'{data}:/data','-v',f'{root}/runtime.py:/runtime.py:ro',
                            '-e','NO_PROXY=catalog,icecast,localhost,127.0.0.1','-e','ALCE_TEST_NEWS='+os.getenv('ALCE_TEST_NEWS','0'),'alce-catalog-validation','python','/runtime.py']),
                ('liquidsoap',['-e','ICECAST_SOURCE_PASSWORD=fixture-source','-e','NO_PROXY=catalog,icecast,localhost,127.0.0.1',
                               '-v',f'{data}:/data','-v',f'{script}:/radio.liq:ro',IMAGE,'liquidsoap','/radio.liq'])]:
                container = tag+'-'+name
                docker('run','-d','--name',container,'--network',tag,
                       '-e','HTTP_PROXY=','-e','HTTPS_PROXY=','-e','ALL_PROXY=',
                       '-e','http_proxy=','-e','https_proxy=','-e','all_proxy=',*args)
                containers.append(container)
                if name != 'liquidsoap': time.sleep(2)
            port = docker('port',tag+'-icecast','8000').split(':')[-1]
            base = f'http://127.0.0.1:{port}'
            for attempt in range(40):
                try:
                    with urllib.request.urlopen(base+'/status-json.xsl',timeout=2) as response:
                        status=json.load(response)
                    if status['icestats'].get('source'): break
                except Exception: pass
                time.sleep(1)
            else: raise AssertionError('Icecast source did not become ready')
            source = status['icestats']['source']
            assert isinstance(source,dict), 'Must have exactly one global source'
            def listen():
                with urllib.request.urlopen(base+'/alce.mp3',timeout=15) as response:
                    if os.getenv('ALCE_TEST_EMERGENCY')=='1':
                        chunks=[]
                        while not capture_stop.is_set(): chunks.append(response.read(8192))
                        return b''.join(chunks)
                    return response.read(960000 if os.getenv('ALCE_TEST_NEWS')=='1' else 360000)
            capture_stop=threading.Event()
            with concurrent.futures.ThreadPoolExecutor(2) as executor:
                futures=[executor.submit(listen) for _ in range(2)]
                try:
                    if os.getenv('ALCE_TEST_EMERGENCY')=='1':
                        def wait_for(predicate, description, limit=50):
                            deadline=time.monotonic()+limit
                            while time.monotonic()<deadline:
                                if predicate(): return
                                time.sleep(.25)
                            raise AssertionError(description)
                        event_path=data/'events.jsonl'
                        wait_for(lambda: event_path.exists() and len(event_path.read_text().splitlines())>=7,
                                 'Main program did not play the validated full cycle')
                        # Ignore earlier cold-boot fallback events: wait for THIS outage.
                        activations=docker('logs',tag+'-liquidsoap').count('EMERGENCY active')
                        # Stop the whole planner process, not just one mocked method.
                        docker('pause',tag+'-catalog')
                        wait_for(lambda: docker('logs',tag+'-liquidsoap').count('EMERGENCY active')>activations,
                                 'Fallback never activated after prefetch drained')
                        time.sleep(6) # Move past the Icecast burst of formerly queued main audio.
                        with urllib.request.urlopen(base+'/alce.mp3',timeout=15) as response:
                            sample=response.read(64000)
                        sample_path=root/'emergency.mp3'; sample_path.write_bytes(sample)
                        pcm=subprocess.run(['ffmpeg','-v','error','-i',str(sample_path),'-ac','1','-ar','8000',
                                            '-f','s16le','-'],check=True,capture_output=True).stdout
                        samples=array.array('h'); samples.frombytes(pcm)
                        if sys.byteorder!='little': samples.byteswap()
                        windows=[samples[index:index+800] for index in range(0,len(samples)-799,800)]
                        rms=[math.sqrt(sum(value*value for value in window)/len(window)) for window in windows]
                        assert len(rms)>=20 and min(rms)>100, ('Emergency silent 100ms window', rms)
                        # Restore the same planner; fallback history safety is covered by unit tests.
                        resumptions=docker('logs',tag+'-liquidsoap').count('EMERGENCY ended / planner resumed')
                        docker('unpause',tag+'-catalog')
                        wait_for(lambda: docker('logs',tag+'-liquidsoap').count('EMERGENCY ended / planner resumed')>resumptions,
                                 'Main program failed to resume at a natural boundary')
                        time.sleep(5)
                        logs=docker('logs',tag+'-liquidsoap')
                        assert 'Error while parsing XML playlist' not in logs,logs
                        assert 'Error while parsing SCPLS playlist' not in logs,logs
                        assert 'EMERGENCY fallback ready' in logs,logs
                        print(json.dumps({'emergency_audio_min_rms':round(min(rms)),
                                          'silent_100ms_windows':0,'planner_resumed':True,
                                          'playlist_parser_errors':0}))
                finally:
                    capture_stop.set()
                    if os.getenv('ALCE_TEST_EMERGENCY')=='1':
                        subprocess.run(DOCKER+['unpause',tag+'-catalog'],capture_output=True)
                captures=[future.result() for future in futures]
            shared = captures[0][100000:140000]
            assert shared in captures[1], 'Listeners must receive the same encoded signal'
            if os.getenv('ALCE_TEST_EMERGENCY')!='1':
                logs=docker('logs',tag+'-liquidsoap')
                assert 'EMERGENCY active' not in logs, 'Normal track boundaries must not switch to emergency'
            events=[json.loads(line) for line in (data/'events.jsonl').read_text().splitlines()]
            types=[e['type'] for e in events]
            expected=(['MUSIC','NEWS_INTRO','NEWS_DROP','MUSIC','STATION_ID','MUSIC','STATION_ID','MUSIC','JINGLE','MUSIC']
                      if os.getenv('ALCE_TEST_NEWS')=='1' else ['MUSIC','STATION_ID','MUSIC','STATION_ID','MUSIC','JINGLE','MUSIC'])
            assert types[:len(expected)]==expected,types
            gaps=[]
            for current, following in zip(events, events[1:]):
                if os.getenv('ALCE_TEST_EMERGENCY')=='1':
                    # HTTP callbacks cannot report timing while their entire process is paused.
                    continue
                delta=following['time']-current['time']
                assert abs(delta-current['duration'])<.25, (current, delta)
                if current['type'] in ('STATION_ID','JINGLE','NEWS_INTRO','NEWS_DROP'):
                    assert delta>=current['duration']-.1, 'Short content truncated'
                gaps.append(abs(delta-current['duration']))
            (root/'capture.mp3').write_bytes(captures[0])
            levels=volume_detect(root/'capture.mp3', start_seconds=10)
            whole=volume_detect(root/'capture.mp3')
            direct=volume_detect(cache/'music.mp3')
            print(json.dumps({'audio_stage':stage,'input_volume':direct,'icecast_volume':levels,'whole_capture_volume':whole}))
            if stage=='production': require_audible(levels)
            subprocess.run(['ffmpeg','-v','error','-xerror' ,'-i',str(root/'capture.mp3'),'-f','null','-'],check=True)
            print(json.dumps({'single_source':True,'listeners':2,'same_encoded_signal':True,
                              'events':len(events),'first_types':types[:len(expected)],
                              'max_boundary_timing_error_ms':round(max(gaps)*1000) if gaps else None,
                              'short_content_complete':True if gaps else None,'stream_decodes':True},ensure_ascii=False))
        except Exception:
            for name in containers:
                print(name, docker('logs','--tail','40',name))
            result = subprocess.run(DOCKER+['exec',tag+'-liquidsoap','ls','-la','/data/cache'], capture_output=True, text=True)
            print(result.stdout, result.stderr)
            raise
        finally:
            for container in reversed(containers):
                subprocess.run(DOCKER+['rm','-f',container],capture_output=True)
            subprocess.run(DOCKER+['network','rm',tag],capture_output=True)
            subprocess.run(DOCKER+['image','rm',tag+'-icecast'],capture_output=True)

if __name__ == '__main__': main()
