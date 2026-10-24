"""Translate private article spools into lifetime-scoped public snapshots."""
from contextlib import ExitStack
from datetime import datetime, timezone
from heapq import merge
from operator import attrgetter

from .articles import ArticleStats
from .extensions import CapturedArticle
from .pipeline import ArticleStore, _article_input, _article_stream_factory


class Snapshot:
    def __init__(self, context, workspace):
        self._languages = tuple(context.languages)
        self._captured_at = datetime.now(timezone.utc)
        self._invalid_articles = 0
        self._store = ArticleStore(workspace)
        self._batches = {}
        self._active = set()
        self._closed = False
        self._capture(context)

    @property
    def languages(self):
        return self._languages

    @property
    def captured_at(self):
        return self._captured_at

    @property
    def invalid_articles(self):
        return self._invalid_articles

    def _capture(self, context):
        stats = ArticleStats()
        try:
            for article in _article_stream_factory(context, stats, self.captured_at)():
                self._store.append(article.lang, article)
            self._invalid_articles = stats.skipped
        except BaseException:
            self.close()
            raise

    def _require_open(self):
        if self._closed:
            raise ValueError('Captured site is closed')

    def _sorted_batch(self, language):
        if language not in self._batches:
            self._batches[language] = self._store.sorted(language)
        return self._batches[language]

    def _read_original(self, language):
        self._require_open()
        if language is not None and language not in self.languages:
            raise ValueError('Captured language is disabled')
        languages = (language,) if language is not None else sorted(self.languages)
        with ExitStack() as cleanup:
            batches = []
            for lang in languages:
                reader = iter(self._sorted_batch(lang))
                cleanup.callback(reader.close)
                batches.append(reader)
            yield from merge(*batches, key=attrgetter('datetime'), reverse=True)

    def original_articles(self, language=None):
        self._require_open()
        source = self._read_original(language)
        self._active.add(source)
        try:
            while True:
                self._require_open()
                try:
                    article = next(source)
                except StopIteration:
                    return
                yield article
        finally:
            self._active.discard(source)
            source.close()

    def articles(self, language=None):
        for article in self.original_articles(language):
            yield CapturedArticle(
                article.title, article.slug, article.lang, article.date, article.datetime,
                article.description, article.tags, article.url, article.policy, _article_input(article),
                article.modified, article.author, article.image, article.indexing, article.translation,
            )

    def close(self):
        self._closed = True
        with ExitStack() as cleanup:
            cleanup.callback(self._store.close)
            cleanup.callback(self._batches.clear)
            cleanup.callback(self._active.clear)
            for source in tuple(self._active):
                cleanup.callback(source.close)
