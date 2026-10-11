"""Radioagência provider: RSS enclosure or official article audio, never third parties/TTS."""
import email.utils
import html
import logging
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import config
from catalogs import read_url

log = logging.getLogger('radio')


def official(url, audio=False):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and (host == 'ebc.com.br' or host.endswith('.ebc.com.br'))
                and not parsed.username and not parsed.fragment and parsed.port in (None, 443)
                and (not audio or parsed.path.lower().endswith('.mp3')))
    except (ValueError, TypeError):
        return False


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not official(newurl):
            raise ValueError('Non-official news redirect')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch_official(url):
    if not official(url):
        raise ValueError('Non-official source')
    with urllib.request.build_opener(OfficialRedirects()).open(
            urllib.request.Request(url, headers={'User-Agent': 'RadioAlceServer/2.0'}), timeout=10) as response:
        data = response.read(2 * 1024 ** 2 + 1)
        if len(data) > 2 * 1024 ** 2:
            raise ValueError('News document too large')
        return data


def duration(value):
    try:
        parts = value.strip().split(':')
        total = 0
        for part in parts:
            total = total * 60 + float(part)
        return total
    except (ValueError, AttributeError):
        return 0


def parse_rss(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD not allowed')
    root = ET.fromstring(data)
    result = {}
    for node in root.findall('.//item'):
        fields = {child.tag.split('}')[-1]: (child.text or '').strip() for child in node}
        try:
            published = email.utils.parsedate_to_datetime(fields.get('pubDate', '')).timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
        article, title = fields.get('link', ''), fields.get('title', '')
        if not title or not official(article):
            continue
        audio = next((child.get('url') for child in node if child.tag.split('}')[-1] in ('enclosure', 'content')
                      and official(child.get('url'), audio=True) and
                      (not child.get('type') or child.get('type').startswith('audio/'))), None)
        length = duration(fields.get('duration', ''))
        if not length:
            match = re.search(r'class=[\"\'][^\"\']*hms[^\"\']*[\"\'][^>]*>([0-9:]+)', fields.get('description', ''))
            length = duration(match[1]) if match else 0
        id = fields.get('guid') or article
        result[id] = {'id': id, 'type': 'NEWS_DROP', 'title': title, 'publishedAt': published,
                      'articleUrl': article, 'url': audio, 'duration': length,
                      'source': 'Radioagência Nacional', 'artist': 'Radioagência Nacional',
                      'category': fields.get('category', '')}
    return sorted(result.values(), key=lambda item: item['publishedAt'], reverse=True)


class AudioLinks(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.audio = base, None

    def handle_starttag(self, tag, attrs):
        if self.audio or tag not in ('audio', 'source', 'a', 'button'):
            return
        attributes = dict(attrs)
        for key in ('data-source', 'src', 'href', 'data-permalink'):
            url = urljoin(self.base, html.unescape(attributes.get(key) or ''))
            if official(url, audio=True):
                self.audio = url
                return


def resolve_audio(base, page):
    if not official(base):
        return None
    parser = AudioLinks(base)
    parser.feed(page)
    return parser.audio


class RemoteNewsProvider:
    def __init__(self, clock=time.time, fetch=fetch_official):
        self.clock, self.fetch = clock, fetch
        self.items = []
        self.refreshed = 0

    def refresh(self):
        if self.clock() - self.refreshed < config.NEWS_REFRESH:
            return
        self.refreshed = self.clock()
        try:
            self.items = parse_rss(self.fetch(config.RSS_URL))
            log.info('NEWS RSS refreshed; items=%s', len(self.items))
        except Exception as error:
            log.warning('NEWS RSS unavailable (%s); music continues', type(error).__name__)

    def eligible(self, played):
        return [item for item in self.items if item['id'] not in played and
                0 <= self.clock() - item['publishedAt'] <= config.NEWS_MAX_AGE and
                (not item['duration'] or config.NEWS_MIN_DURATION <= item['duration'] <= config.NEWS_MAX_DURATION)]

    def candidate(self, played, prepare):
        for item in self.eligible(played)[:8]:
            try:
                url = item['url'] or resolve_audio(item['articleUrl'], self.fetch(item['articleUrl']).decode('utf-8'))
                if not official(url, audio=True):
                    continue
                prepared = prepare(dict(item, url=url))
                if config.NEWS_MIN_DURATION <= prepared['duration'] <= config.NEWS_MAX_DURATION:
                    log.info('NEWS selected id=%s published=%s audio resolved=true', item['id'], item['publishedAt'])
                    return prepared
            except Exception as error:
                log.warning('NEWS audio ignored id=%s (%s)', item['id'], type(error).__name__)
        return None
