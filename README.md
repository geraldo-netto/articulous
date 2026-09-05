# Articulous Static Site Generator

[![Articulous](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml/badge.svg)](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml)

A parallel, incremental static site generator powered by **XML + XSLT**.
Written in Python, with lxml and optional SaxonC transformation backends.

---

## 🚀 Features

- XML-based article format
- XSLT-driven rendering pipeline (per-section engine choice)
- Streaming, parallel build execution
- Incremental caching of input, stylesheet, engine and output-path fingerprints
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

The project root is the current working directory, regardless of where
the executable or `--config` file lives. Configured source/output paths
are resolved beneath that root; output must not overlap a source tree.
The active configuration must stay outside the output tree. Builds reject
configuration paths inside it, including symlink aliases, before publishing.

The build cache (`.build-cache.json` by default) lives at the project
root. Only the filename component of `build.cache_file` is used. Entries
live under `__output_roots__`, keyed by resolved output directory.
Ownership is also stored beside each output tree in
`.output.articulous-ownership.json` by default, under the output lock.
Deleting, corrupting or switching the fingerprint cache preserves this
ownership history, so deleted/private pages can still be pruned.

Legacy cache manifests migrate automatically when no ownership file
exists. Flat caches bind to the output used for the first upgraded build;
target the existing output before changing directories. A populated output
tree without ownership history, or an invalid ownership file, stops the
build. Restore ownership from backup or choose an empty output tree.
Use `--force` for a rebuild that keeps ownership history.

Builds targeting the same output directory share a lock beside it
(`.output.articulous.lock` by default), independent of cache filename.
Builds sharing a cache also share a cache lock
(`..build-cache.json.articulous.lock` by default). A conflicting build
fails immediately rather than waiting. Lock files remain after release;
stale or malformed metadata is recovered once the OS lock is available.
Cache, log, lock and ownership paths must stay separate from configuration, source
trees, output trees and each other.
Configuration, cache, log, lock and ownership paths must refer to regular files
when they exist; directories, FIFOs and devices are rejected. File opens
are nonblocking and verify the opened file type before reading or writing.

---

## 📝 Article Format (XML)

Place regular `.xml` article files anywhere inside `content/`. Discovery
does not traverse symlinked subdirectories; symlinked article files and
special files are skipped with an error. Each article has this shape:

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
  the filename stem is used instead. Slugs contain lowercase ASCII
  letters, digits and hyphens; articles producing an empty slug are skipped.
- `<date>` must be ISO‑8601 (`YYYY-MM-DD` or full timestamp). Articles
  with a missing or invalid date are skipped with a warning. Dates and
  publication timestamps without a timezone are treated as UTC; timezone
  offsets are converted to UTC for sorting and scheduling.
- `<lang>` is validated against `site.languages`; values outside the
  configured set fall back to `site.default_language`.
- `<status>` may be `published`, `unlisted`, `draft`, `private`, or
  `scheduled`. Unknown statuses are skipped with a warning.
- `unlisted` pages are generated but excluded from index/tag pages, RSS,
  sitemap, and search. `draft` and `private` articles are skipped.
- `scheduled` articles publish only when `<publish-at>` is present and
  its ISO-8601 timestamp has been reached. A missing or invalid timestamp
  keeps the article unpublished and emits a warning. Scheduling is
  evaluated during a build; no background scheduler runs the generator.
- Targeted builds remove retired article pages within their selected
  sections, languages, and slugs using the persistent ownership sidecar.
  Legacy cache ownership is used only to initialize a missing sidecar;
  deleting the fingerprint cache does not disable pruning. Unselected
  pages remain untouched.
- Language and slug filters limit article pages. Selected RSS, sitemap
  and search sections use all articles eligible for those sections;
  selected index and tag sections use complete listings for each selected
  language. `--slug` does not narrow shared listings or feeds.

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
Dependency validation checks all configured sections, even with `--only`.
The content directory and `xsl/pages/` must already exist.

---

## ⚙️ Running the Generator

Requires Python 3.11 or newer and a Unix platform with `fcntl` file
locking. CI runs on Ubuntu with Python 3.11–3.14. Native Windows execution
is not supported by the current filesystem layer.

From a repository checkout, install the package in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Create a site with the source directories and templates shown above,
then run from that site's root using the installed command:

```sh
articulous
```

For a site containing the source checkout, the executable shim also works:

```sh
chmod +x sitegen.py
./sitegen.py
```

…or run the package directly:

```sh
python3 -m articulous
```

All three entry points use the current working directory as the project
root. This repository includes a test site under `tests/fixtures/site/`;
the repository root itself does not contain production content/templates.

---

## 🔧 Useful CLI Options

```
--config FILE        Use a custom config file (default: config.json)
--only SECTIONS      Build only specific sections, comma-separated
                     (articles,index,tags,rss,sitemap,search).
                     Unknown names raise immediately.
--lang LANG          Limit article/listing languages; global feeds stay complete
                     (repeat to pass many)
--slug SLUG          Limit article slugs; shared listings/feeds stay complete
                     (repeat to pass many)
--dry-run            Plan without publishing outputs or saving the build cache
--force              Rebuild selected outputs and assets, ignoring fingerprints
-v, --verbose        Enable DEBUG-level logging
```

Examples:

```sh
./sitegen.py --only articles
./sitegen.py --only index,tags --verbose
./sitegen.py --lang en --lang fr --slug hello-world
./sitegen.py --dry-run
```

`--force` retains section, language and slug filters. Assets are mirrored
on every non-dry build, including section-limited builds. `--dry-run`
still validates dependencies and paths, scans inputs, acquires lock
files, creates temporary planning files and writes configured logs.
A missing configuration file is still created with defaults.
Asset destination and cached-path checks run in both modes; a dry run
rejects the same existing symlinks, hardlinks, and invalid cached paths
without copying or pruning assets. Filesystem changes after validation
can still cause a later live build to fail.

---

## 🛠️ Configuration

Configuration lives in `config.json`. If the file is missing, defaults
are written automatically on first run. Malformed existing configuration
fails fast instead of being overwritten.
Supplied JSON is merged with defaults, so omitted settings use their
defaults. Unknown keys and invalid value types are rejected.

| Block         | Keys                                                                                                |
| ------------- | --------------------------------------------------------------------------------------------------- |
| `paths`       | `content_dir`, `output_dir`, `xsl_dir`, `assets_dir`                                                |
| `engines`     | per‑section engine (`articles`, `index`, `tags`, `rss`, `sitemap`, `search`) → `"lxml"` or `"saxonc"`; `"native"` also supported for `sitemap` and `search` (their default) |
| `saxonc`      | `home` — path to the SaxonC install (optional; `Transform` is discovered on `PATH` when null)       |
| `site`        | `site_name`, `base_url`, `languages`, `default_language`, `pagination.per_page`, `pagination.rss_items` |
| `urls`        | URL patterns for `article`, `index`, `tag`, `rss`, `sitemap`, `search` (e.g. `/{lang}/articles/{slug}/`) |
| `build`       | `cache_file`, `parallelism` (`"auto"` or a positive int), `force_full_build` (boolean)              |
| `logging`     | `level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), `file` (optional path)                       |

`pagination.per_page` must be positive; `pagination.rss_items` may be
zero, producing an empty RSS feed. `languages` must be non-empty and
unique, and must contain `default_language`. Language identifiers may
contain only ASCII letters, digits, hyphens and underscores, such as
`en`, `fr`, `pt-BR` or `en_US`, so they remain safe URL and filesystem
segments.

With `parallelism="auto"`, the worker count is `max(4, os.cpu_count() or 4)`
unless a configured engine resolves to SaxonC, in which case it is
`os.cpu_count() or 4`. An explicit positive integer overrides that choice.

An unknown engine name aborts the build immediately. Requesting
`"saxonc"` without a usable `Transform` executable falls back to lxml;
an invalid explicit `saxonc.home` also emits a warning. A configured
home is checked at `<home>/bin/Transform`; `PATH` discovery is used only
when no home is set. A nonzero exit from a selected executable fails
the build; it does not trigger fallback.

lxml blocks XSLT document reads and writes to files or network resources,
while allowing local stylesheet includes/imports. SaxonC is invoked with
`-ext:off`, `-xi:off` and `--allowedProtocols:#none` to disable external
functions, XInclude and external resource URIs.
SaxonC requires standalone stylesheets: external includes and imports
are rejected. Use lxml for stylesheets with local includes or imports.
Planning captures stylesheet bytes and local dependencies; workers compile
that snapshot, so edits during execution apply on the next build. Fingerprints
include the captured bytes and logical file URIs. With lxml, relative includes
resolve beside the configured stylesheet path, including symlink paths;
`xml:base` applies consistently to both capture and compilation. Every dependency
must be a regular file and is opened without blocking on special files.
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
patterns must include one and must not end with a slash. Patterns are
local paths: schemes, hosts, query strings, fragments, percent escapes,
backslashes, and control characters are rejected before a build starts.
Generated paths and their components are checked against the target
filesystem's byte limits during planning, before assets or pages are
published. Oversized slugs or tags fail the build; they are not truncated.

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

Generated pages and feeds replace individual files atomically; a whole
build is not transactional. A live generated target or any parent component
that is a symlink is rejected. Publication and temporary-file cleanup stay
anchored to the original destination directory. A directory replacement
detected after rendering aborts publication; cleanup and permission changes
use the original directory and file descriptors.
Before publishing, the ownership file records
all previously owned and planned paths. Interrupted builds retain this
record, including old paths from failed URL changes. Retry without
`--only`, `--lang` or `--slug`: recovery forces a full rebuild and prunes
obsolete paths, then clears the recovery flag. A dry run leaves that flag
intact. Inspect partial output before deploying after a failed build.
Existing unowned targets enter recovery ownership only after publication
replaces them; a planned target that was never replaced is preserved.

The entire `output/assets/` subtree belongs to the asset mirror. Every build
compares its entries with the source: removed source entries and manual
additions in the destination are pruned, even after cache loss or a failed
first build. For example, deleting `assets/retired.pdf` removes its public
copy; adding `output/assets/manual.pdf` without a source copy removes it too.
Keep files you want published in the source assets directory. A missing
source assets directory removes the entire mirrored assets tree.
Destination file/directory mismatches are repaired, including the mirror
root when the source directory is empty.
Entries inside the asset source must be regular files or directories;
destination symlinks and hardlinks are rejected. Asset copies are not
atomic. For predictable pruning, reserve the output tree for generated
files and avoid adding symlinks inside it.
Pruning removes stale generated symlinks themselves, preserving their
targets. A symlink in a stale path's parent directories aborts pruning.
If a stale owned file has become a directory, pruning stops and preserves
the directory and its contents. Move or remove it explicitly before retrying;
page/feed ownership never authorizes recursive directory deletion.
Cached generated outputs must remain regular files. A directory, FIFO, or
device in place of a cached page/feed stops both normal and forced builds;
the entry is preserved for explicit recovery. Remove or relocate it, then
retry. A missing generated file is rebuilt automatically.

---

## 🧪 Development

The package is covered by a pytest suite with fixture‑based site builds,
unit tests, and section‑order fuzz tests. Coverage is enforced at
**100 % line + branch** via `pytest-cov` (`--cov-fail-under=100`).
The tests use lxml for XML validation; `xmllint` is not required. In an
activated virtual environment, install the test extra and run:

```sh
python -m pip install -e ".[test]"
python -m pytest
ruff check --no-cache .
ruff check --no-cache --select C901 --config 'lint.mccabe.max-complexity = 10' articulous tests
pyright --pythonpath .venv/bin/python
```

CI installs the versions in `uv.lock` with
`uv sync --locked --extra test --no-build --no-install-project` for each
Python version. To use those locked dependencies locally, run that
command with `--python 3.11` (or another CI version), then use the tools
in `.venv/bin/`. The CI job runs Ruff, Pyright and pytest; the separate
`C901` command above checks the repository's complexity limit.

---

## 📜 License

MIT
