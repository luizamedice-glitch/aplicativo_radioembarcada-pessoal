"""One SQLite checkpoint on the Docker volume. Commits are playback acknowledgements."""
import json
import sqlite3
import threading


class Storage:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plays (id TEXT PRIMARY KEY, played_at REAL, artist TEXT);
            CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, played_at REAL);
        ''')

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))

    def history(self):
        with self.lock:
            return {row[0]: {'played_at': row[1], 'artist': row[2]} for row in
                    self.db.execute('SELECT id,played_at,artist FROM plays')}

    def played_news(self):
        with self.lock:
            return {row[0] for row in self.db.execute('SELECT id FROM news')}

    def started(self, item, checkpoint, now, retention, limit, news_limit):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                            ('programming', json.dumps(checkpoint)))
            if item['type'] == 'MUSIC':
                self.db.execute('INSERT OR REPLACE INTO plays VALUES (?,?,?)',
                                (item['id'], now, item.get('artist', '').strip().casefold()))
                self.db.execute('DELETE FROM plays WHERE played_at < ?', (now - retention,))
                self.db.execute('DELETE FROM plays WHERE id NOT IN '
                                '(SELECT id FROM plays ORDER BY played_at DESC LIMIT ?)', (limit,))
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_music', json.dumps(item['id'])))
            elif item['type'] == 'NEWS_DROP':
                self.db.execute('INSERT OR REPLACE INTO news VALUES (?,?)', (item['id'], now))
                self.db.execute('DELETE FROM news WHERE id NOT IN '
                                '(SELECT id FROM news ORDER BY played_at DESC LIMIT ?)', (news_limit,))
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_news_played_at', json.dumps(now)))

    def reconcile(self, ids):
        with self.lock, self.db:
            for id in list(self.history()):
                if id not in ids:
                    self.db.execute('DELETE FROM plays WHERE id=?', (id,))

    def close(self):
        self.db.close()
