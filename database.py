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
            return {
                'words_count': words_count,
                'links_count': links_count,
            }

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
