"""Bounded sitemap serialization and disk-backed shard inputs."""
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .filesystem import TempWorkspace


MAX_URLS = 50_000
MAX_BYTES = 52_428_800


def sitemap_entry(value) -> tuple[str, str]:
    if isinstance(value, dict):
        return value["url"], value["modified"]
    return value, ""


def native_entry(value) -> str:
    url, modified = sitemap_entry(value)
    lastmod = f"<lastmod>{escape(modified)}</lastmod>" if modified else ""
    return f"<url><loc>{escape(url)}</loc>{lastmod}</url>"


def _envelope(tag: str) -> tuple[str, str]:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<{tag} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"</{tag}>",
    )


def write_document(output, values, tag, render, max_urls, max_bytes) -> None:
    header, footer = _envelope(tag)
    size = len((header + footer).encode("utf-8"))
    if size > max_bytes:
        raise ValueError("Sitemap exceeds the 50 MiB limit")
    with output.open("w", encoding="utf-8") as out:
        out.write(header)
        for count, value in enumerate(values, start=1):
            entry = render(value)
            size += len(entry.encode("utf-8"))
            if count > max_urls or size > max_bytes:
                raise ValueError("Sitemap exceeds the 50,000 URL or 50 MiB limit")
            out.write(entry)
        out.write(footer)


def write_index(output, urls) -> None:
    write_document(output, urls, "sitemapindex", _index_entry, MAX_URLS, MAX_BYTES)


def _index_entry(url: str) -> str:
    return f"<sitemap><loc>{escape(url)}</loc></sitemap>"


_FRAME = struct.Struct('>I')


@dataclass(frozen=True)
class SitemapSlice:
    path: Path
    offset: int
    size: int
    fingerprint: str
    integrity: str

    def values(self):
        digest = hashlib.sha256()
        with self.path.open("rb") as source:
            source.seek(self.offset)
            remaining = self.size
            while remaining:
                header, entry = _read_frame(source, remaining)
                remaining -= len(header) + len(entry)
                digest.update(header)
                digest.update(entry)
                yield entry
        if digest.hexdigest() != self.integrity:
            raise ValueError("Sitemap spool changed")

    def write(self, output) -> None:
        header, footer = _envelope("urlset")
        with output.open("wb") as out:
            out.write(header.encode("utf-8"))
            for entry in self.values():
                out.write(entry)
            out.write(footer.encode("utf-8"))


def _read_frame(source, remaining):
    header = source.read(min(_FRAME.size, remaining))
    if len(header) != _FRAME.size:
        raise ValueError("Sitemap spool truncated")
    size, = _FRAME.unpack(header)
    if size == 0 or size > remaining - _FRAME.size:
        raise ValueError("Sitemap spool changed")
    entry = source.read(size)
    if len(entry) != size:
        raise ValueError("Sitemap spool truncated")
    return header, entry


class _ShardBuilder:
    def __init__(self, out, envelope_size):
        self.out = out
        self.envelope_size = envelope_size
        self._reset()

    def _reset(self):
        self.start = self.out.tell()
        self.size = self.envelope_size
        self.count = 0
        self.fingerprint = hashlib.sha256()
        self.integrity = hashlib.sha256()

    def append(self, value, entry):
        header = _FRAME.pack(len(entry))
        self.out.write(header)
        self.out.write(entry)
        self.integrity.update(header)
        self.integrity.update(entry)
        encoded = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        self.fingerprint.update(encoded)
        self.size += len(entry)
        self.count += 1

    def finish(self):
        shard = SitemapSlice(Path(self.out.name), self.start, self.out.tell() - self.start,
                             self.fingerprint.hexdigest(), self.integrity.hexdigest())
        self._reset()
        return shard


def _reject_sitemap(values, problem):
    for _ in values:
        pass
    raise ValueError(problem)


def partition_sitemap(workspace: TempWorkspace, values, max_urls: int, max_bytes: int) -> list[SitemapSlice]:
    values = iter(values)
    envelope_size = len("".join(_envelope("urlset")).encode("utf-8"))
    if envelope_size > max_bytes:
        _reject_sitemap(values, "Sitemap envelope exceeds the 50 MiB limit")
    shards = []
    with workspace.named_file("w+b") as out:
        shard = _ShardBuilder(out, envelope_size)
        for value in values:
            entry = native_entry(value).encode("utf-8")
            if envelope_size + len(entry) > max_bytes:
                _reject_sitemap(values, "Sitemap entry exceeds the 50 MiB limit")
            if shard.count >= max_urls or shard.size + len(entry) > max_bytes:
                shards.append(shard.finish())
            shard.append(value, entry)
        shards.append(shard.finish())
    return shards
