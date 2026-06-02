import sqlite3
from contextlib import contextmanager
from pathlib import Path


class RhymesRepository:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _prepare_group(word, rhymes):
        return list(dict.fromkeys(rhyme for rhyme in rhymes if rhyme != word))

    def init_db(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS rhymes (
                    word TEXT NOT NULL,
                    rhyme TEXT NOT NULL,
                    UNIQUE(word, rhyme)
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS challenge_subscriptions (
                    chat_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_send_at TEXT NOT NULL,
                    last_sent_at TEXT
                )
                '''
            )

    def get_rhymes(self, word):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rhyme FROM rhymes WHERE word = ?', (word,))
            return [row[0] for row in cursor.fetchall()]

    def get_stats(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(DISTINCT word), COUNT(*) FROM rhymes')
            words_count, links_count = cursor.fetchone()
            cursor.execute(
                'SELECT COUNT(*) FROM challenge_subscriptions WHERE enabled = 1'
            )
            subscribers_count = cursor.fetchone()[0]
            return {
                'words_count': words_count,
                'links_count': links_count,
                'subscribers_count': subscribers_count,
            }

    def get_rhyme_counts(self, words):
        unique_words = list(dict.fromkeys(words))
        if not unique_words:
            return {}
        placeholders = ','.join('?' for _ in unique_words)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT word, COUNT(*)
                FROM rhymes
                WHERE word IN ({placeholders})
                GROUP BY word
                ''',
                unique_words,
            )
            counts = dict(cursor.fetchall())
        return {word: counts.get(word, 0) for word in unique_words}

    def subscribe_to_challenges(self, chat_id, next_send_at):
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO challenge_subscriptions (chat_id, enabled, next_send_at)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    enabled = 1,
                    next_send_at = excluded.next_send_at
                ''',
                (chat_id, next_send_at),
            )

    def ensure_challenge_subscription(self, chat_id, next_send_at):
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT OR IGNORE INTO challenge_subscriptions (
                    chat_id,
                    enabled,
                    next_send_at
                )
                VALUES (?, 1, ?)
                ''',
                (chat_id, next_send_at),
            )

    def unsubscribe_from_challenges(self, chat_id):
        with self._connect() as conn:
            conn.execute(
                'UPDATE challenge_subscriptions SET enabled = 0 WHERE chat_id = ?',
                (chat_id,),
            )

    def get_challenge_subscription(self, chat_id):
        with self._connect() as conn:
            cursor = conn.execute(
                '''
                SELECT chat_id, enabled, next_send_at, last_sent_at
                FROM challenge_subscriptions
                WHERE chat_id = ?
                ''',
                (chat_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            'chat_id': row[0],
            'enabled': bool(row[1]),
            'next_send_at': row[2],
            'last_sent_at': row[3],
        }

    def get_due_challenge_subscriptions(self, now, limit=100):
        with self._connect() as conn:
            cursor = conn.execute(
                '''
                SELECT chat_id, next_send_at
                FROM challenge_subscriptions
                WHERE enabled = 1 AND next_send_at <= ?
                ORDER BY next_send_at
                LIMIT ?
                ''',
                (now, limit),
            )
            return [
                {'chat_id': row[0], 'next_send_at': row[1]}
                for row in cursor.fetchall()
            ]

    def mark_challenge_sent(self, chat_id, sent_at, next_send_at):
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE challenge_subscriptions
                SET last_sent_at = ?, next_send_at = ?
                WHERE chat_id = ?
                ''',
                (sent_at, next_send_at, chat_id),
            )

    def backup(self, backup_path):
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source:
            target = sqlite3.connect(backup_path)
            try:
                source.backup(target)
            finally:
                target.close()

    def add_rhyme_group(self, word, rhymes):
        rhymes = self._prepare_group(word, rhymes)
        with self._connect() as conn:
            cursor = conn.cursor()
            for rhyme in rhymes:
                cursor.execute(
                    'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                    (word, rhyme),
                )
                cursor.execute(
                    'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                    (rhyme, word),
                )
            for i in range(len(rhymes)):
                for j in range(len(rhymes)):
                    if i != j:
                        cursor.execute(
                            'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                            (rhymes[i], rhymes[j]),
                        )

    def replace_rhymes_for_word(self, word, new_rhymes):
        new_rhymes = self._prepare_group(word, new_rhymes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rhyme FROM rhymes WHERE word = ?', (word,))
            old_rhymes = [row[0] for row in cursor.fetchall()]
            words_to_update = set([word] + old_rhymes)
            placeholders = ','.join('?' for _ in words_to_update)
            params = list(words_to_update)
            cursor.execute(
                f'DELETE FROM rhymes WHERE word IN ({placeholders}) OR rhyme IN ({placeholders})',
                params + params,
            )

            for rhyme in new_rhymes:
                cursor.execute(
                    'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                    (word, rhyme),
                )
                cursor.execute(
                    'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                    (rhyme, word),
                )

            for i in range(len(new_rhymes)):
                for j in range(len(new_rhymes)):
                    if i != j:
                        cursor.execute(
                            'INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)',
                            (new_rhymes[i], new_rhymes[j]),
                        )
