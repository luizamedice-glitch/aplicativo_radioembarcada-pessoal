#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
mode="${1:---deploy}"
if [[ "$mode" != --deploy && "$mode" != --check ]]; then
  echo 'Uso: ./setup.sh [--check|--deploy]' >&2
  exit 2
fi
command -v docker >/dev/null
command -v openssl >/dev/null
command -v python3 >/dev/null

if [[ ! -f .env ]]; then
  printf 'ICECAST_SOURCE_PASSWORD=%s\nICECAST_ADMIN_PASSWORD=%s\nFREETTS_API_KEY=\nFREETTS_VOICE=pt-BR-AntonioNeural\nTZ=America/Sao_Paulo\nSTATS_USER=radioadmin\nSTATS_PASSWORD=%s\n' \
    "$(openssl rand -hex 16)" "$(openssl rand -hex 16)" "$(openssl rand -hex 12)" > .env
fi
# Append optional settings to old installations without replacing existing credentials.
if ! grep -q '^FREETTS_API_KEY=' .env; then printf '\nFREETTS_API_KEY=\n' >> .env; fi
if ! grep -q '^STATS_USER=' .env; then printf '\nSTATS_USER=radioadmin\n' >> .env; fi
if ! grep -q '^STATS_PASSWORD=' .env; then printf 'STATS_PASSWORD=%s\n' "$(openssl rand -hex 12)" >> .env; fi
chmod 600 .env
set -a
. ./.env
set +a
: "${ICECAST_SOURCE_PASSWORD:?Senha source ausente}"
: "${ICECAST_ADMIN_PASSWORD:?Senha admin ausente}"

backup="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"
cp .env docker-compose.yml "$backup/"
cp -a liquidsoap "$backup/"
if [[ -f icecast/icecast.xml ]]; then cp icecast/icecast.xml "$backup/icecast.xml"; fi
python3 - <<'PY'
import os
from pathlib import Path
import xml.etree.ElementTree as ET
path = Path('icecast/icecast.xml')
root = ET.parse('icecast/icecast.xml.template')
for item in root.iter():
    if item.text == 'SOURCE_PASS_PLACEHOLDER': item.text = os.environ['ICECAST_SOURCE_PASSWORD']
    if item.text == 'ADMIN_PASS_PLACEHOLDER': item.text = os.environ['ICECAST_ADMIN_PASSWORD']
root.write(path, encoding='utf-8', xml_declaration=True)
path.chmod(0o600)
PY
# Readable public scripts for the unprivileged Liquidsoap image; secrets remain 0600.
chmod 755 liquidsoap
chmod 644 liquidsoap/*.liq
docker compose config --quiet
docker compose pull liquidsoap
docker compose build catalog icecast stats
docker compose run --rm --no-deps liquidsoap liquidsoap --check /radio.liq
printf 'Sintaxe validada; backup local em %s.\n' "$backup"
if [[ "$mode" == --check ]]; then
  echo 'Nenhum serviço existente foi reiniciado.'
  exit 0
fi

# Prepare catalogs and next audio while the existing Icecast/Liquidsoap are still running.
docker compose up -d --no-deps --wait --wait-timeout 600 catalog
docker compose exec -T catalog python - <<'PY'
import datetime, pathlib, sqlite3
source = pathlib.Path('/data/station.sqlite3')
if source.exists():
    directory = pathlib.Path('/data/backups'); directory.mkdir(exist_ok=True)
    target = directory / ('station-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.sqlite3')
    with sqlite3.connect(source) as db, sqlite3.connect(target) as copy: db.backup(copy)
    print('Checkpoint SQLite salvo no volume persistente.')
PY
# A planned source/encoder cutover can briefly reconnect listeners; never use compose down -v.
docker compose up -d --wait --wait-timeout 120 icecast liquidsoap stats
docker compose ps
python3 - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/alce.mp3', timeout=15) as stream:
    assert stream.status == 200 and len(stream.read(8192)) == 8192
print('Stream /alce.mp3 respondeu HTTP 200 com áudio; confirme a sequência ouvindo.')
PY
