"""Disk-backed ownership checks for article and listing URLs projected by partial builds."""
from contextlib import closing, contextmanager
from functools import partial
import sqlite3


def _claim(database, url):
    try:
        database.execute("INSERT INTO routes VALUES (?)", (url.rstrip('/'),))
    except sqlite3.IntegrityError as error:
        raise ValueError(f'Duplicate generated output path: {url}') from error


@contextmanager
def projection_route_check(cli, sections, sitemap_listings):
    generated_listings = not (sitemap_listings and 'sitemap' in sections) or {'tags', 'index'} <= sections
    complete = 'articles' in sections and not (cli.only_langs or cli.only_slugs) and generated_listings
    if complete or sections <= {'articles'}:
        yield None
        return
    with closing(sqlite3.connect('')) as database:
        database.execute("PRAGMA cache_size = -512")
        database.execute("CREATE TABLE routes (url TEXT PRIMARY KEY) WITHOUT ROWID")
        yield partial(_claim, database)
