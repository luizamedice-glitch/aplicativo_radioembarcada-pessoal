#!/usr/bin/env bash
# Run from a NEW checkout on the EC2; keep the active installation for rollback.
set -euo pipefail
umask 077
cd "$(dirname "$0")"
RELEASE_DIR="$PWD"
CURRENT=$(docker inspect radio-alce-liquidsoap --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}')
PROJECT=$(docker inspect radio-alce-liquidsoap --format '{{ index .Config.Labels "com.docker.compose.project" }}')
test -d "$CURRENT"
test -n "$PROJECT"
if [[ "$(realpath "$CURRENT")" == "$(realpath "$RELEASE_DIR")" ]]; then
  echo 'Execute este script em um novo clone, separado da instalação ativa.' >&2
  exit 1
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$HOME/radio-alce-backups/transitions-$STAMP"
mkdir -p "$BACKUP"
chmod 700 "$HOME/radio-alce-backups" "$BACKUP"
cp -a "$CURRENT/." "$BACKUP/"
{
  printf '#!/usr/bin/env bash\nset -euo pipefail\ncd %q\n' "$BACKUP"
  printf 'COMPOSE_PROJECT_NAME=%q LIQUIDSOAP_CONFIG=%q docker compose up -d --build --no-deps --force-recreate catalog liquidsoap\n' "$PROJECT" "$BACKUP/liquidsoap/radio.liq"
} > "$BACKUP/rollback-transitions.sh"
printf 'Backup: %s\nRollback: bash %q\n' "$BACKUP" "$BACKUP/rollback-transitions.sh"
cp "$CURRENT/.env" .env
chmod 600 .env
export COMPOSE_PROJECT_NAME="$PROJECT"
export LIQUIDSOAP_CONFIG="$RELEASE_DIR/liquidsoap/radio.liq"
# Persist selectors so subsequent docker compose commands use the same volume/script.
python3 - <<'PY'
import os
from pathlib import Path
p = Path('.env')
lines = [line for line in p.read_text().splitlines()
         if not line.startswith(('COMPOSE_PROJECT_NAME=', 'LIQUIDSOAP_CONFIG='))]
lines += ['COMPOSE_PROJECT_NAME=' + os.environ['COMPOSE_PROJECT_NAME'],
          'LIQUIDSOAP_CONFIG=' + os.environ['LIQUIDSOAP_CONFIG']]
p.write_text('\n'.join(lines) + '\n')
PY
# No service changes until config, build, tests and Liquidsoap syntax all pass.
docker compose config --quiet
docker compose build catalog
docker compose run --rm --no-deps -v "$PWD/tests:/tests:ro" catalog \
  python -m unittest discover -s /tests -v
docker compose run --rm --no-deps liquidsoap liquidsoap --check /radio.liq
printf 'Rollback disponível em: %s\n' "$BACKUP"
# Icecast stays up; emergency sustains the existing encoder while catalog warms.
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 600 catalog
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 liquidsoap
# Verify the files INSIDE the running containers, not just the checkout.
LOCAL_LIQ=$(sha256sum liquidsoap/radio.liq | cut -d' ' -f1)
ACTIVE_LIQ=$(docker exec radio-alce-liquidsoap sha256sum /radio.liq | cut -d' ' -f1)
test "$LOCAL_LIQ" = "$ACTIVE_LIQ"
for FILE in audio_boundaries.py audio_cache.py sync_catalog.py config.py; do
  LOCAL_SUM=$(sha256sum "$FILE" | cut -d' ' -f1)
  ACTIVE_SUM=$(docker exec radio-alce-catalog sha256sum "/app/$FILE" | cut -d' ' -f1)
  test "$LOCAL_SUM" = "$ACTIVE_SUM"
done
docker compose ps
printf '\nArquivos ativos conferidos. Ouça MUSIC → INSERT → MUSIC.\n'
printf 'Logs: cd %q && docker compose logs --since 5m catalog liquidsoap | grep -E "AUDIO edges|AUDIO envelope|AUDIO pipeline"\n' "$RELEASE_DIR"
printf 'Rollback (sem apagar volume):\ncd %q\n' "$BACKUP"
printf 'COMPOSE_PROJECT_NAME=%q LIQUIDSOAP_CONFIG=%q docker compose up -d --build --no-deps --force-recreate catalog liquidsoap\n' "$PROJECT" "$BACKUP/liquidsoap/radio.liq"
