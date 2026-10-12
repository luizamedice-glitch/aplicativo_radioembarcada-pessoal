"""Private Horoscopo Em Dia prototype: daily RSS, chapter cuts and one sign per slot.

Not licensed for public rebroadcast. Disabled by default.
"""
import email.utils
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from audio_cache import probe

log = logging.getLogger("radio")
SIGNS = ("Áries", "Touro", "Gêmeos", "Câncer", "Leão", "Virgem",
         "Libra", "Escorpião", "Sagitário", "Capricórnio", "Aquário", "Peixes")
APPLE_LOOKUP = "https://itunes.apple.com/lookup?id=1721237546&entity=podcast"
CHAPTER = re.compile(r"(?m)(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–:]\s*(Áries|Touro|Gêmeos|Câncer|Leão|Virgem|Libra|Escorpião|Sagitário|Capricórnio|Aquário|Peixes|Encerramento|Mensagem Final)\b", re.I)

def seconds(value):
    out = 0
    for part in value.split(":"):
        out = out * 60 + int(part)
    return out

def https_url(value):
    from urllib.parse import urlsplit
    p = urlsplit(value or "")
    return p.scheme == "https" and bool(p.hostname) and p.username is None and p.password is None and p.port in (None, 443)

def read_limited(url, limit=10_000_000):
    if not https_url(url):
        raise ValueError("Non-HTTPS podcast URL")
    request = urllib.request.Request(url, headers={"User-Agent": "RadioAlcePrivateTest/1.0"})
    with urllib.request.urlopen(request, timeout=15) as r:
        if not https_url(r.url):
            raise ValueError("Redirected to non-HTTPS URL")
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Response exceeds limit")
    return data

def parse_episodes(feed, date_key):
    if b"<!DOCTYPE" in feed.upper() or b"<!ENTITY" in feed.upper():
        raise ValueError("XML DTD not permitted")
    root = ET.fromstring(feed)
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        if not re.search(r"horóscopo do dia", title, re.I):
            continue
        pub = item.findtext("pubDate", "")
        try:
            published = email.utils.parsedate_to_datetime(pub).astimezone(ZoneInfo(config.TIME_ZONE))
        except (ValueError, TypeError, OverflowError):
            continue
        # Prefer the date named in the title, which can differ from UTC publication day.
        normalized = title.casefold()
        day = str(int(date_key[-2:]))
        month = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")[int(date_key[5:7])-1]
        if not (re.search(r"\b" + day + r"\s+de\s+" + month + r"\s+de\s+" + date_key[:4] + r"\b", normalized)
                or (published.date().isoformat() == date_key and date_key[:4] in normalized)):
            continue
        enclosure = next((e.attrib.get("url") for e in item if e.tag.split("}")[-1] == "enclosure"
                          and (e.attrib.get("type", "").startswith("audio/") or e.attrib.get("url", "").lower().endswith(".mp3"))), None)
        if not https_url(enclosure):
            continue
        desc = next((e.text or "" for e in item if e.tag.split("}")[-1] in ("description", "encoded") and e.text), "")
        desc = html.unescape(re.sub(r"<[^>]*>", " ", desc)).replace("\xa0", " ")
        matches = [(m.group(2).casefold(), seconds(m.group(1))) for m in CHAPTER.finditer(desc)]
        if len(matches) < 13 or [n for n, _ in matches[:12]] != [s.casefold() for s in SIGNS] or matches[12][0] not in ("encerramento", "mensagem final"):
            continue
        points = [t for _, t in matches[:13]]
        if points != sorted(set(points)) or points[0] < 0 or points[-1] > 3600:
            continue
        return {"url": enclosure, "points": points, "title": title, "date": date_key}
    return None

class HoroscopeProvider:
    def __init__(self, directory, clock=time.time, fetch=read_limited):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clock, self.fetch = clock, fetch
        self._date = None
        self._episode = None
        self._next_attempt = 0

    def slot(self, boundary, storage, reserved):
        if not config.HOROSCOPE_PRIVATE_TEST:
            return None
        local = datetime.fromtimestamp(boundary, ZoneInfo(config.TIME_ZONE))
        index = local.hour - 7
        if not 0 <= index < 12:
            return None
        date_key = local.date().isoformat()
        slot = date_key + ":" + str(index)
        if storage.get("horoscope_last_slot") == slot or slot in reserved:
            return None
        if self._date != date_key:
            self._date, self._episode, self._next_attempt = date_key, None, 0
            # Keep at most the most recent private preview recordings.
            cutoff = self.clock() - 3 * 86400
            for old in self.directory.glob("horoscope-*.mp3"):
                try:
                    if old.stat().st_mtime < cutoff:
                        old.unlink()
                except OSError:
                    pass
        if self._episode is None and self.clock() >= self._next_attempt:
            try:
                lookup = json.loads(self.fetch(APPLE_LOOKUP))
                feed_url = lookup["results"][0]["feedUrl"]
                self._episode = parse_episodes(self.fetch(feed_url), date_key)
            except Exception as e:
                log.warning("HOROSCOPE feed unavailable: %s", type(e).__name__)
            self._next_attempt = self.clock() + 15 * 60
        if not self._episode:
            return None
        return self._segment(index, slot)

    def _segment(self, index, slot):
        episode = self._episode
        digest = hashlib.sha256((episode["url"] + slot).encode()).hexdigest()
        target = self.directory / ("horoscope-" + digest + ".mp3")
        if not target.is_file():
            source = self.directory / ("horoscope-source-" + hashlib.sha256(episode["url"].encode()).hexdigest() + ".mp3")
            if not source.is_file():
                raw = self.fetch(episode["url"], limit=40_000_000)
                tmp = source.with_suffix(".part")
                tmp.write_bytes(raw)
                probe(tmp)
                tmp.replace(source)
            start, end = episode["points"][index:index+2]
            temp = target.with_suffix(".part")
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y",
                                "-ss", str(start), "-to", str(end), "-i", str(source),
                                "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", str(temp)],
                               check=True, timeout=45, capture_output=True)
                probe(temp)
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
        return {"id": "horoscope:" + slot, "type": "HOROSCOPE",
                "title": "Horóscopo — " + SIGNS[index], "artist": "Horóscopo Em Dia",
                "path": str(target), "duration": probe(target), "horoscope_slot": slot}
