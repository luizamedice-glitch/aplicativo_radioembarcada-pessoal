"""Real-time local HTTP MP3 fixture; no requests to production."""
import importlib.util
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
spec=importlib.util.spec_from_file_location('hls',Path(__file__).resolve().parents[1] / 'pipeline.py')
hls=importlib.util.module_from_spec(spec); spec.loader.exec_module(hls)
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=500:duration=5','-c:a','libmp3lame','-b:a','128k',str(root/'tone.mp3')],check=True)
    data=(root/'tone.mp3').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type','audio/mpeg'); self.end_headers()
            try:
                while True:
                    for offset in range(0,len(data),1600):
                        self.wfile.write(data[offset:offset+1600]); self.wfile.flush(); time.sleep(.1)
            except (BrokenPipeError, ConnectionResetError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    proc=subprocess.Popen(hls.command(f'http://127.0.0.1:{server.server_port}/alce.mp3',root,'b'*32),stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            path=root/'live.m3u8'
            if path.exists() and len(hls.segments(path.read_text()))>=2: break
            time.sleep(.5)
        assert proc.poll() is None
        names=hls.segments(path.read_text()); assert len(names)>=2
        import re
        print('HTTP live input → HLS: advancing playlist, complete segments',len(names))
        r=subprocess.run(['ffmpeg','-hide_banner','-i',str(root/names[0]),'-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
        assert float(re.search(r'mean_volume: ([\d.-]+)', r.stderr)[1]) > -40
        assert float(re.search(r'max_volume: ([\d.-]+)', r.stderr)[1]) > -25
        print('\n'.join(line for line in r.stderr.splitlines() if '_volume:' in line))
    finally:
        proc.terminate();proc.wait(timeout=5);server.shutdown()
