"""Schema-independent translation discovery, provenance selection and job execution."""
import os

from .languages import validate_languages
from .source_transactions import fingerprint


def _xml_names(directory):
    try:
        entries = os.scandir(directory)
    except FileNotFoundError:
        return []
    with entries:
        return sorted(entry.name for entry in entries if entry.name.endswith('.xml') and entry.is_file())


def collect_variants(content, languages):
    validate_languages(languages)
    catalog = {}
    for language in languages:
        directory = content / language
        for name in _xml_names(directory):
            catalog.setdefault(name, {})[language] = directory / name
    return catalog


def resolve_original(path, root, read_origin):
    root = root.resolve()
    seen = set()
    while path.is_file():
        resolved = path.resolve()
        if resolved in seen:
            return None
        if not resolved.is_relative_to(root):
            raise ValueError(f'Translation original escapes content directory: {path}')
        seen.add(resolved)
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
