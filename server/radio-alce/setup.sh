#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  SOURCE_PASS="$(openssl rand -hex 16)"
  ADMIN_PASS="$(openssl rand -hex 16)"
  printf 'ICECAST_SOURCE_PASSWORD=%s\nICECAST_ADMIN_PASSWORD=%s\n' "$SOURCE_PASS" "$ADMIN_PASS" > .env
  chmod 600 .env
fi

set -a
. ./.env
set +a

sed   -e "s/SOURCE_PASS_PLACEHOLDER/${ICECAST_SOURCE_PASSWORD}/g"   -e "s/ADMIN_PASS_PLACEHOLDER/${ICECAST_ADMIN_PASSWORD}/g"   icecast/icecast.xml.template > icecast/icecast.xml

docker compose build
docker compose up -d
docker compose ps
