"""Bounded sitemap serialization and disk-backed shard inputs."""
import hashlib
import json
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


@dataclass(frozen=True)
class SitemapSlice:
    path: Path
    offset: int
    size: int
    fingerprint: str

    def values(self):
        digest = hashlib.sha256()
        with self.path.open("rb") as source:
            source.seek(self.offset)
            remaining = self.size
            while remaining:
                line = source.readline(remaining)
                if not line:
                    raise ValueError("Sitemap spool truncated")
                remaining -= len(line)
                digest.update(line)
                yield json.loads(line)
        if digest.hexdigest() != self.fingerprint:
            raise ValueError("Sitemap spool changed")


def partition_sitemap(workspace: TempWorkspace, values, max_urls: int, max_bytes: int) -> list[SitemapSlice]:
    envelope_size = len("".join(_envelope("urlset")).encode("utf-8"))
    if envelope_size > max_bytes:
        raise ValueError("Sitemap envelope exceeds the 50 MiB limit")
    shards = []
    with workspace.named_file("w+b") as out:
        start, count, size = 0, 0, envelope_size
        digest = hashlib.sha256()
        for value in values:
            entry_size = len(native_entry(value).encode("utf-8"))
            if envelope_size + entry_size > max_bytes:
                raise ValueError("Sitemap entry exceeds the 50 MiB limit")
            if count >= max_urls or size + entry_size > max_bytes:
                shards.append(SitemapSlice(Path(out.name), start, out.tell() - start, digest.hexdigest()))
                start, count, size = out.tell(), 0, envelope_size
                digest = hashlib.sha256()
            encoded = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
            out.write(encoded)
            digest.update(encoded)
            count += 1
            size += entry_size
        shards.append(SitemapSlice(Path(out.name), start, out.tell() - start, digest.hexdigest()))
    return shards
