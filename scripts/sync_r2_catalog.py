#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import quote


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return default


def main():
    parser = argparse.ArgumentParser(
        description="Regenera music_catalog.json a partir da listagem atual do Cloudflare R2."
    )
    parser.add_argument("--keys", required=True, help="JSON contendo a lista de chaves do R2.")
    parser.add_argument("--output", required=True, help="Caminho de saída do music_catalog.json.")
    parser.add_argument("--public-base", required=True, help="Base pública r2.dev, sem barra final.")
    parser.add_argument("--old-catalog", help="Catálogo anterior para preservar metadados e versão.")
    parser.add_argument("--station", default="Rádio Alce")
    parser.add_argument("--prefix", default="music/")
    args = parser.parse_args()

    raw_keys = load_json(args.keys, [])
    if not isinstance(raw_keys, list):
        raise SystemExit("A listagem do R2 não é uma lista JSON válida.")

    prefix = args.prefix
    keys = sorted(
        key for key in raw_keys
        if isinstance(key, str)
        and key.startswith(prefix)
        and key.lower().endswith(".mp3")
    )

    if not keys:
        raise SystemExit(f"Nenhum MP3 encontrado sob o prefixo {prefix!r}; catálogo não foi publicado.")

    old_catalog = load_json(args.old_catalog, {}) if args.old_catalog else {}
    try:
        old_version = int(old_catalog.get("version", 0))
    except (TypeError, ValueError):
        old_version = 0

    old_items = old_catalog.get("items", [])
    previous_by_id = {
        item.get("id"): item
        for item in old_items
        if isinstance(item, dict) and item.get("id")
    }

    previous_by_url = {item.get("url"): item for item in old_items
                       if isinstance(item, dict) and item.get("id") and item.get("url")}
    base = args.public_base.rstrip("/")
    items = []

    for key in keys:
        track_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        filename = PurePosixPath(key).name
        url = f"{base}/{quote(key, safe='/')}"
        previous = previous_by_url.get(url) or previous_by_id.get(track_id, {})
        track_id = previous.get("id") or track_id

        item = {
            "id": track_id,
            "type": "MUSIC",
            "title": previous.get("title") or PurePosixPath(filename).stem,
            "artist": previous.get("artist") or "",
            "url": f"{base}/{quote(key, safe='/')}",
        }
        items.append(item)

    catalog = {
        "station": old_catalog.get("station") or args.station,
        "version": old_version + 1,
        "items": items,
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Versão: {catalog['version']}")
    print(f"Músicas: {len(items)}")


if __name__ == "__main__":
    main()
