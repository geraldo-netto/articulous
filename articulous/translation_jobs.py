"""Schema-independent translation discovery, provenance selection and job execution."""
import re
from collections.abc import Sequence
from .source_transactions import fingerprint


def validate_languages(languages):
    if not isinstance(languages, Sequence) or isinstance(languages, (str, bytes)):
        raise ValueError('Languages must be distinct, nonempty language codes')
    if (any(not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', code) for code in languages)
            or len({code.casefold() for code in languages}) != len(languages)):
        raise ValueError('Languages must be distinct, nonempty language codes')


def collect_variants(content, languages):
    validate_languages(languages)
    catalog = {}
    for language in languages:
        directory = content / language
        for path in sorted(directory.glob('*.xml')):
            catalog.setdefault(path.name, {})[language] = path
    return catalog


def resolve_original(path, root, read_origin):
    root = root.resolve()
    seen = set()
    while path.is_file() and path.resolve() not in seen:
        if not path.resolve().is_relative_to(root):
            raise ValueError(f'Translation original escapes content directory: {path}')
        seen.add(path.resolve())
        origin = read_origin(path)
        if origin is None:
            return None
        language, source = origin
        if source is None:
            return language, path
        path = source
    return None


def select_original(variants, default_language, resolve):
    originals = {}
    for path in variants.values():
        original = resolve(path)
        if original is not None:
            language, source = original
            originals[language] = source
    if not originals:
        raise ValueError('Translation original unavailable (missing or cyclic provenance)')
    language = default_language if default_language in originals else sorted(originals)[0]
    return language, originals[language]


def pending_jobs(jobs, generated, current, *, force=False):
    pending = []
    for job in jobs:
        if job.target.exists():
            if not generated(job.target):
                continue
            if not force and current(job):
                continue
        pending.append(job)
    return pending


def file_budget(jobs, limit):
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError('Translation file limit must be a non-negative integer')
    return list(jobs[:limit] if limit else jobs)


def run_jobs(jobs, execute):
    snapshots = {job.target: fingerprint(job.target) for job in jobs}
    if len(snapshots) != len(jobs):
        raise ValueError('Duplicate translation target')
    for job in jobs:
        if fingerprint(job.target) != snapshots[job.target]:
            raise ValueError(f'Translation target changed: {job.target}')
        execute(job)
