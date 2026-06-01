import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from database import RhymesRepository


class RhymesRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'rhymes.db'
        self.repository = RhymesRepository(self.db_path)
        self.repository.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_rhyme_group_creates_bidirectional_links_without_duplicates(self):
        self.repository.add_rhyme_group('вдруг', ['друг', 'круг', 'друг'])

        self.assertEqual(set(self.repository.get_rhymes('вдруг')), {'друг', 'круг'})
        self.assertEqual(set(self.repository.get_rhymes('друг')), {'вдруг', 'круг'})
        self.assertEqual(set(self.repository.get_rhymes('круг')), {'вдруг', 'друг'})

    def test_replace_rhymes_removes_old_group_and_creates_new_group(self):
        self.repository.add_rhyme_group('вдруг', ['друг', 'круг'])

        self.repository.replace_rhymes_for_word('вдруг', ['внук', 'мрут'])

        self.assertEqual(set(self.repository.get_rhymes('вдруг')), {'внук', 'мрут'})
        self.assertEqual(self.repository.get_rhymes('друг'), [])
        self.assertEqual(self.repository.get_rhymes('круг'), [])
        self.assertEqual(set(self.repository.get_rhymes('внук')), {'вдруг', 'мрут'})

    def test_get_stats_counts_words_and_directional_links(self):
        self.repository.add_rhyme_group('вдруг', ['друг', 'круг'])

        self.assertEqual(
            self.repository.get_stats(),
            {'words_count': 3, 'links_count': 6},
        )

    def test_backup_creates_readable_copy(self):
        self.repository.add_rhyme_group('вдруг', ['друг'])
        backup_path = Path(self.temp_dir.name) / 'backups' / 'rhymes.db'

        self.repository.backup(backup_path)

        with closing(sqlite3.connect(backup_path)) as conn:
            rows = conn.execute(
                'SELECT word, rhyme FROM rhymes ORDER BY word, rhyme'
            ).fetchall()
        self.assertEqual(rows, [('вдруг', 'друг'), ('друг', 'вдруг')])


if __name__ == '__main__':
    unittest.main()
