"""Sequential translation retries/cache with caller-owned prompt and cleanup sponsors."""
import hashlib
import http.client
import json
import time
import urllib.error
from .markup import placeholder_signature, usable_translation
from .translation_contracts import TranslationCache, TranslationProvider


class Translator:
    def __init__(self, provider: TranslationProvider, cache: TranslationCache, prompt, normalize, log, *, retries=2):
        if type(retries) is not int or retries < 0:
            raise ValueError('Translation retries must be a non-negative integer')
        self.provider = provider
        self.cache = cache
        self.prompt = prompt
        self.normalize = normalize
        self.log = log
        self.retries = retries
        self.calls = 0
        self.cache_hits = 0

    @property
    def model(self):
        return self.provider.model

    def _system(self, source, target, keep_placeholders):
        return self.prompt(source, target, keep_placeholders)

    def _key(self, text, source, target, keep_placeholders=True, *, system=None):
        if system is None:
            system = self._system(source, target, keep_placeholders)
        value = [self.provider.identity, system, source, target, text, keep_placeholders]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    def _cached(self, key):
        return self.cache.get(key)

    def _store(self, key, value):
        self.cache.put(key, value)

    def _post(self, system, user):
        return self.provider.post(system, user)

    def _valid(self, value, wanted, markup):
        return isinstance(value, str) and usable_translation(value, wanted, markup)

    def _cache_hit(self, key, wanted, markup):
        value = self._cached(key)
        if value is None:
            return None
        if self._valid(value, wanted, markup):
            self.cache_hits += 1
            return value
        self.cache.delete(key)
        return None

    def _attempt(self, system, text, wanted, markup, attempt):
        try:
            self.calls += 1
            candidate = self._post(system, text)
        except (urllib.error.URLError, KeyError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
            self.log(f'    ! endpoint error ({error}); retry {attempt + 1}')
            time.sleep(2)
            return None
        if isinstance(candidate, str):
            candidate = self.normalize(candidate)
        if self._valid(candidate, wanted, markup):
            return candidate
        self.log(f'    ! empty translation or placeholder mismatch; retry {attempt + 1}')
        return None

    def translate(self, text, source, target, keep_placeholders=True):
        if not text.strip():
            return text
        system = self._system(source, target, keep_placeholders)
        key = self._key(text, source, target, keep_placeholders, system=system)
        wanted = placeholder_signature(text) if keep_placeholders else []
        hit = self._cache_hit(key, wanted, keep_placeholders)
        if hit is not None:
            return hit
        for attempt in range(self.retries + 1):
            candidate = self._attempt(system, text, wanted, keep_placeholders, attempt)
            if candidate is not None:
                self._store(key, candidate)
                return candidate
        return None
