#!/usr/bin/env python3
import json
import os
import time
import urllib.request

URL = "https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/music_catalog.json"
OUT = "/data/music.m3u"

while True:
    try:
        request = urllib.request.Request(
            URL,
            headers={
                "User-Agent": "RadioAlceServer/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            catalog = json.load(response)

        urls = [
            item.get("url")
            for item in catalog.get("items", [])
            if item.get("type") == "MUSIC" and item.get("url")
        ]

        if urls:
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write("#EXTM3U\n")
                for url in urls:
                    handle.write(url + "\n")
            os.replace(tmp, OUT)
            print(f"Catálogo atualizado: {len(urls)} músicas", flush=True)
        else:
            print("Catálogo sem músicas; mantendo playlist anterior.", flush=True)

    except Exception as exc:
        print(f"Falha ao atualizar catálogo: {exc}", flush=True)

    time.sleep(60)
