# Articulous Static Site Generator

[![Articulous](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml/badge.svg)](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml)

A fast, parallel, incremental static site generator powered by **XML + XSLT**.
Written in Python, with optional SaxonC acceleration for high-performance builds.

---

## 🚀 Features

- XML-based article format
- XSLT-driven rendering pipeline (per-section engine choice)
- Streaming, parallel build execution
- Incremental caching (only rebuilds changed files)
- Multi‑language sites with per‑article `<lang>`
- Automatic generation of:
  - Article pages
  - Paginated index pages
  - Tag pages
  - RSS feed
  - Sitemap
  - Search index (JSON)
- Dry‑run mode
- Section‑limited builds (`--only`), language and slug filters
- Optional SaxonC support (auto‑falls back to lxml)

---

## 📁 Project Structure

A site that uses Articulous is laid out like this:

```
your-site/
├── sitegen.py              # executable shim (ships with this repo)
├── articulous/             # the Python package (ships with this repo)
├── config.json             # site configuration
├── content/                # your .xml articles (any sub‑tree layout)
│   ├── en/
│   │   └── hello-world.xml
│   └── fr/
│       └── bonjour.xml
├── xsl/
│   └── pages/
│       ├── article.xsl
│       ├── index.xsl
│       ├── tags.xsl
│       ├── rss.xsl
│       ├── sitemap.xsl
│       └── search.xsl
├── assets/                 # images, css, js, mirrored into output/
└── output/                 # build target (created on first run)
    ├── en/
    │   ├── articles/<slug>/index.html
    │   ├── page/<n>/index.html
    │   └── tags/<tag>/index.html
    ├── assets/
    ├── rss.xml
    ├── sitemap.xml
    └── search.json
```

The build cache (`.build-cache.json` by default) is written next to
`sitegen.py` and is safe to delete to force a full rebuild. Concurrent
builds targeting the same output directory share a lock beside that
directory (`.output.articulous.lock` for the default output), independent
of the cache filename. Stale or malformed lock metadata is recovered
automatically; the cache must not use the lock's path.

---

## 📝 Article Format (XML)

Place your articles anywhere inside `content/`. Each file:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<article>
  <title>Hello World</title>
  <date>2024-01-01</date>
  <description>My first article.</description>
  <lang>en</lang>           <!-- optional; falls back to site.default_language -->
  <status>published</status> <!-- optional; default is published -->
  <publish-at>2024-01-01T00:00:00</publish-at> <!-- only used by scheduled -->
  <tag>intro</tag>
  <tag>welcome</tag>
</article>
```

Notes:

- The slug is derived from `<title>` (URL‑safe). If the title is empty,
  the filename stem is used instead.
- `<date>` must be ISO‑8601 (`YYYY-MM-DD` or full timestamp). Articles
  with a missing or invalid date are skipped with a warning.
- `<lang>` is validated against `site.languages`; values outside the
  configured set fall back to `site.default_language`.
- `<status>` may be `published`, `unlisted`, `draft`, `private`, or
  `scheduled`. Unknown statuses are skipped with a warning.
- `unlisted` pages are generated but excluded from index/tag pages, RSS,
  sitemap, and search. `draft` and `private` articles are skipped.
- `scheduled` articles publish only when `<publish-at>` is present and
  its ISO-8601 timestamp has passed. A missing timestamp keeps the article
  skipped; an invalid timestamp is skipped with a warning.
- Targeted builds remove retired article pages within their selected
  sections, languages, and slugs while preserving unselected pages.

---

## 🧩 Required XSL Templates

The generator requires these files inside `xsl/pages/`:

- `article.xsl`
- `index.xsl`
- `tags.xsl`
- `rss.xsl`

The default `native` engine writes sitemap and search outputs incrementally,
so it does not need `sitemap.xsl` or `search.xsl`. Those templates are
required only when their section is configured with `lxml` or `saxonc`.

---

## ⚙️ Running the Generator

Either invoke the shim:

```sh
chmod +x sitegen.py
./sitegen.py
```

…or run the package directly:

```sh
python3 -m articulous
```

Both forms are equivalent.

---

## 🔧 Useful CLI Options

```
--config FILE        Use a custom config file (default: config.json)
--only SECTIONS      Build only specific sections, comma-separated
                     (articles,index,tags,rss,sitemap,search).
                     Unknown names raise immediately.
--lang LANG          Limit build to specific languages (repeat to pass many)
--slug SLUG          Build only specific article slugs (repeat to pass many)
--dry-run            Do not write output files
--force              Ignore cache and rebuild everything
-v, --verbose        Enable DEBUG-level logging
```

Examples:

```sh
./sitegen.py --only articles
./sitegen.py --only index,tags --verbose
./sitegen.py --lang en --lang fr --slug hello-world
./sitegen.py --dry-run
```

---

## 🛠️ Configuration

Configuration lives in `config.json`. If the file is missing, defaults
are written automatically on first run. Malformed existing configuration
fails fast instead of being overwritten.

| Block         | Keys                                                                                                |
| ------------- | --------------------------------------------------------------------------------------------------- |
| `paths`       | `content_dir`, `output_dir`, `xsl_dir`, `assets_dir`                                                |
| `engines`     | per‑section engine (`articles`, `index`, `tags`, `rss`, `sitemap`, `search`) → `"lxml"` or `"saxonc"` |
| `saxonc`      | `home` — path to the SaxonC install (optional; `Transform` is discovered on `PATH` when null)       |
| `site`        | `site_name`, `base_url`, `languages`, `default_language`, `pagination.per_page`, `pagination.rss_items` |
| `urls`        | URL patterns for `article`, `index`, `tag`, `rss`, `sitemap`, `search` (e.g. `/{lang}/articles/{slug}/`) |
| `build`       | `cache_file`, `parallelism` (`"auto"` or an int), `force_full_build`                                |
| `logging`     | `level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), `file` (optional path)                       |

An unknown engine name in `engines` aborts the build immediately so
typos surface early. Requesting `"saxonc"` without a usable binary
silently falls back to the lxml engine. lxml denies XSLT file/network
access, and SaxonC runs with external functions and XInclude disabled.
The `"native"` engine is available only for `sitemap` and `search`; it
streams those standard formats with bounded memory. Select `lxml` or
`saxonc` for either section when custom XSLT output is required.

Native sitemap builds fail before replacing the published file if they
exceed 50,000 URLs or 50 MiB of uncompressed XML.

URL patterns are validated by section:

| URL key   | Required placeholders | Output shape |
| --------- | --------------------- | ------------ |
| `article` | `{lang}`, `{slug}`    | Directory-style; `index.html` is appended |
| `index`   | `{lang}`, `{page}`    | Directory-style; `index.html` is appended |
| `tag`     | `{lang}`, `{tag}`     | Directory-style; `index.html` is appended |
| `rss`     | none                  | File-style path, such as `/rss.xml` |
| `sitemap` | none                  | File-style path, such as `/sitemap.xml` |
| `search`  | none                  | File-style path, such as `/search.json` |

Directory-style patterns must not end in a file suffix. File-style
patterns must include one.

---

## 📦 Output

Files are written to `output/` according to the configured `urls`
patterns. The `assets/` subtree is reserved for mirrored assets;
generated-page patterns cannot use it. Conflicting generated paths are
rejected before publishing. Defaults produce:

- `output/en/articles/<slug>/index.html`
- `output/en/page/<n>/index.html`
- `output/en/tags/<tag>/index.html`
- `output/assets/...` (incremental mirror of `assets/`)
- `output/rss.xml`
- `output/sitemap.xml`
- `output/search.json`

---

## 🧪 Development

The package is covered by a pytest suite with fixture‑based site builds,
unit tests, and section‑order fuzz tests. Coverage is enforced at
**100 % line + branch** via `pytest-cov` (`--cov-fail-under=100`).
Install `xmllint` first (for example, `libxml2-utils` on Debian/Ubuntu),
then install the Python test dependencies and local lint/type tools.

```sh
pip install -e ".[test]" ruff pyright
pytest
ruff check .
pyright
```

Notes:

- Incremental builds use `.build-cache.json` at the project root.
- `parallelism` defaults to CPU count when set to `"auto"`.
- SaxonC is optional; when its binary is absent the lxml engine is used
  for every section, regardless of `engines` configuration.

---

## 📜 License

MIT
