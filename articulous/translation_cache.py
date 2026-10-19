"""Optional SQLite adapter; context owns connection, clients borrow it."""
from contextlib import closing, contextmanager
import sqlite3


class SqliteCache:
    def __init__(self, connection):
        self.connection = connection

    def get(self, key):
        row = self.connection.execute('SELECT target FROM tr WHERE k = ?', (key,)).fetchone()
        return row[0] if row else None

    def put(self, key, value):
        self.connection.execute('INSERT OR REPLACE INTO tr (k, target) VALUES (?, ?)', (key, value))
        self.connection.commit()

    def delete(self, key):
        self.connection.execute('DELETE FROM tr WHERE k = ?', (key,))
        self.connection.commit()


@contextmanager
def open_cache(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS tr (k TEXT PRIMARY KEY, target TEXT)')
        yield SqliteCache(connection)
