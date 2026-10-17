#!/usr/bin/env python3
import base64
import html
import json
import os
import re
import urllib.request
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

USER = os.getenv('STATS_USER', 'radioadmin')
PASSWORD = os.getenv('STATS_PASSWORD', '')
LOGDIR = Path('/var/log/icecast2')
STATUS_URL = os.getenv('ICECAST_STATUS_URL', 'http://icecast:8000/status-json.xsl')
MOUNT = os.getenv('RADIO_MOUNT', '/alce.mp3')

LINE = re.compile(r'^(?P<ip>\S+) .*? \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) [^"]+" (?P<status>\d{3}) (?P<bytes>\S+)(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?.*$')

def icecast():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=3) as response:
            data = json.load(response)
        source = data.get('icestats', {}).get('source', {})
        if isinstance(source, list):
            source = next((x for x in source if x.get('listenurl','').endswith(MOUNT)), source[0] if source else {})
        return {
            'listeners': int(source.get('listeners', 0) or 0),
            'listener_peak': int(source.get('listener_peak', 0) or 0),
            'server_name': source.get('server_name') or 'Rádio Alce',
            'title': source.get('title') or '',
        }
    except Exception:
        return {'listeners': 0, 'listener_peak': 0, 'server_name': 'Rádio Alce', 'title': '', 'offline': True}

def parse_logs():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    daily = Counter()
    today_ips = set()
    today_connections = 0
    recent = deque(maxlen=20)
    today = now.astimezone().date()
    for path in sorted(LOGDIR.glob('access.log*')):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            m = LINE.match(line)
            if not m or m.group('method') != 'GET' or m.group('path').split('?')[0] != MOUNT or m.group('status') != '200':
                continue
            try:
                ts = datetime.strptime(m.group('ts'), '%d/%b/%Y:%H:%M:%S %z')
            except ValueError:
                continue
            if ts < cutoff:
                continue
            day = ts.astimezone().date().isoformat()
            daily[day] += 1
            if ts.astimezone().date() == today:
                today_connections += 1
                today_ips.add(m.group('ip'))
            recent.appendleft({
                'time': ts.astimezone().strftime('%d/%m %H:%M'),
                'agent': (m.group('ua') or 'Navegador/app')[:90]
            })
    return {
        'connections_today': today_connections,
        'unique_today': len(today_ips),
        'daily': [{'date': d, 'connections': daily[d]} for d in sorted(daily)],
        'recent': list(recent),
    }

def snapshot():
    return {**icecast(), **parse_logs(), 'updated_at': datetime.now().astimezone().strftime('%d/%m/%Y %H:%M:%S')}

def page(data):
    rows = ''.join(f"<tr><td>{html.escape(x['date'])}</td><td>{x['connections']}</td></tr>" for x in data['daily']) or '<tr><td colspan="2">Sem dados</td></tr>'
    recent = ''.join(f"<tr><td>{html.escape(x['time'])}</td><td>{html.escape(x['agent'])}</td></tr>" for x in data['recent']) or '<tr><td colspan="2">Sem conexões recentes</td></tr>'
    offline = '<span class="off">Icecast indisponível</span>' if data.get('offline') else '<span class="on">Ao vivo</span>'
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rádio Alce — Acessos</title><style>
body{{font-family:system-ui,sans-serif;background:#0b0c0e;color:#f3f3f3;margin:0;padding:18px}}main{{max-width:760px;margin:auto}}
h1{{font-size:22px;margin:0 0 6px}}.sub{{color:#aaa;margin-bottom:18px}}.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}
.card{{background:#17191d;border:1px solid #2a2d32;border-radius:16px;padding:16px}}.n{{font-size:34px;font-weight:700}}.l{{color:#aaa;font-size:13px}}
section{{margin-top:18px;background:#17191d;border-radius:16px;padding:16px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px 4px;border-bottom:1px solid #292c31;text-align:left;font-size:14px}}
.on{{color:#66d17a}}.off{{color:#ff7474}}.foot{{color:#888;font-size:12px;margin-top:12px}}@media(max-width:480px){{.cards{{grid-template-columns:1fr 1fr}}.n{{font-size:28px}}}}
</style><meta http-equiv="refresh" content="15"></head><body><main>
<h1>Rádio Alce — Acessos</h1><div class="sub">{offline} · atualizado {html.escape(data['updated_at'])}</div>
<div class="cards"><div class="card"><div class="n">{data['listeners']}</div><div class="l">ouvintes agora</div></div>
<div class="card"><div class="n">{data['listener_peak']}</div><div class="l">pico atual do Icecast</div></div>
<div class="card"><div class="n">{data['connections_today']}</div><div class="l">conexões hoje</div></div>
<div class="card"><div class="n">{data['unique_today']}</div><div class="l">IPs únicos hoje</div></div></div>
<section><h2>Últimos 7 dias</h2><table><tr><th>Data</th><th>Conexões</th></tr>{rows}</table></section>
<section><h2>Conexões recentes</h2><table><tr><th>Horário</th><th>Dispositivo</th></tr>{recent}</table>
<div class="foot">Conexões não equivalem a pessoas únicas: reconexões do navegador/app podem gerar novas entradas.</div></section>
</main></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def auth(self):
        if not PASSWORD:
            return False
        expected = 'Basic ' + base64.b64encode(f'{USER}:{PASSWORD}'.encode()).decode()
        return self.headers.get('Authorization') == expected
    def do_GET(self):
        if not self.auth():
            self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Radio Alce Stats"'); self.end_headers(); return
        data = snapshot()
        if self.path == '/stats.json':
            body = json.dumps(data, ensure_ascii=False).encode()
            ctype = 'application/json; charset=utf-8'
        else:
            body = page(data).encode()
            ctype = 'text/html; charset=utf-8'
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)

ThreadingHTTPServer(('0.0.0.0', 8082), Handler).serve_forever()
