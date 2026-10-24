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
- Optional canonical index roots and empty-language landing pages
- Python APIs for extra pages, route discovery and staged validation
- Opt-in Linux whole-site publication with rollback and journal recovery

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
The sidecar also preserves immutable route metadata, including canonical URLs,
language, category and sitemap eligibility. Cached route metadata is derived;
it cannot override the ownership record.

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

- `<title>`, `<date>`, `<description>`, `<lang>`, `<status>`, and
  `<publish-at>` may each occur at most once, including identical or empty
  occurrences. A duplicate skips the article and emits a warning naming
  its file and field, for example `duplicate singleton field <status>`.
  A successful build retracts previously owned outputs within its selected
  scope. Repeated `<tag>` elements remain valid; each article appears once
  on each tag page.
- Optional `<slug>stable-address</slug>` pins an article URL across title edits.
  Explicit slugs contain 1–128 lowercase ASCII letters/digits with single
  hyphens between segments. Empty, duplicate, nested, and unsafe slugs reject
  the article; colliding generated paths fail before publication. Without
  `<slug>`, the legacy title-derived slug remains; an empty title falls back
  to the filename stem. Articles producing an empty slug are skipped.
  Intentional slug or route changes prune the old owned output on the next
  selected build. Configure a permanent HTTP 301 or 308 redirect from the old
  URL to the new URL at your host/CDN before deployment; the generator cannot
  emit HTTP responses. Include the deployment prefix in both redirect URLs,
  avoid redirect chains, and verify the old URL returns the permanent redirect.
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
- Article pages render the XML captured during metadata and publication
  validation; fingerprints use those same bytes and the captured source URI.
  Bodies are spooled to disk, while shared listings retain metadata only.
  Edits after capture apply on the next build: changing a public article to
  private can still publish its old public snapshot in the current build,
  but cannot publish newly added private text. The next selected build
  retracts the owned page. This is snapshot consistency, not immediate revocation.
- `scheduled` articles publish only when `<publish-at>` is present and
  its ISO-8601 timestamp has been reached. A missing or invalid timestamp
  keeps the article unpublished and emits a warning. Scheduling is
  evaluated once per build, before article discovery; that timestamp governs
  pages, translation links and all shared projections. A captured composition
  uses its capture timestamp. No background scheduler runs the generator.
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

The optional reference structured-data example is enabled per article:

```xml
<structured-data>BlogPosting</structured-data>
<author>Author Name</author>
<image>https://example.com/photo.jpg?w=800&amp;h=600</image>
<modified>2025-02-01T12:00:00Z</modified>
```

`structured-data` accepts `Article` or `BlogPosting`; omission disables JSON-LD.
`author`, `image`, and `modified` are optional and omitted from JSON-LD when
unavailable. An author is one plain-text name of 1–512 characters after trimming
surrounding whitespace. Image URLs must be absolute, URI-encoded HTTP(S),
without credentials or fragments; query parameters are supported. Empty,
malformed, duplicate, and nested metadata fields reject the article.

`articulous-jsonld` contains script-safe JSON-LD with the resolved canonical URL,
UTC publication timestamp from the source date, optional content modification
date, and metadata matching the reference page's visible text. Templates also
receive `articulous-title`, `articulous-description`, `articulous-author`,
`articulous-image`, `articulous-published`, and `articulous-modified`. The reference
template displays those values and emits one `application/ld+json` script when
enabled. Relative-only builds omit JSON-LD because no absolute canonical is
available. Production themes should include only metadata matching their visible
content, following [Article structured-data guidance](https://developers.google.com/search/docs/appearance/structured-data/article).
Large SaxonC metadata strings are embedded as quoted literal parameters in the
temporary captured stylesheet to avoid operating-system argument-size limits.
The source stylesheet remains unchanged.

After adapting and deploying your template, run its public article URL through
Google's [Rich Results Test](https://search.google.com/test/rich-results), or paste
the generated HTML into its code input. Confirm the intended Article/BlogPosting
item, canonical URL, author/image, and dates; investigate errors and relevant
warnings. This repository's tests parse rendered JSON-LD locally; the external
Rich Results Test remains a deployment check.

Use the same `<translation>story-id</translation>` in articles that are actual
translations. IDs contain 1–128 ASCII letters/digits with hyphen or underscore
separators; duplicates within one article, malformed IDs, and nested fields
reject that article. There can be only one indexable page per translation ID
and normalized locale; ambiguity fails before publication. Relationships are
never inferred from titles or slugs. Private, draft, and noindex peers are
excluded; unlisted peers remain indexable by default.

Templates receive `articulous-translation` and `articulous-alternates`.
The latter is a pre-escaped HTML fragment of self-inclusive reciprocal
`<link rel="alternate" hreflang="..." href="..."/>` elements, sorted by locale.
Emit it in the head with `<xsl:value-of select="$articulous-alternates"
disable-output-escaping="yes"/>`, as in the reference template. Relative-only
builds omit the fragment. Metadata fingerprints track peer URLs and membership.

Annotation locales use ISO language, optional script, and optional region codes
(for example `en`, `en-US`, `zh-Hant-TW`); `en_US` normalizes to `en-US` without
changing the route. Unsupported codes fail translated builds. Bundled identifiers
come from the [IANA registry](https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry)
and ISO 3166-1 alpha-2; numeric and reserved regions such as `419`, `EU`, and `UK`
are excluded, following [hreflang guidance](https://developers.google.com/search/docs/specialty/international/localized-versions).
Filtered builds still discover all peers. If a filter would leave an unselected
peer with stale reciprocal links, the build fails before publishing; run a full
build after relationship changes. Unchanged groups support targeted builds.

Set top-level `"robots": {"enabled": true}` to generate `output/robots.txt`
alongside the sitemap (including `--only sitemap`). Default: disabled.
The supported rules allow crawling all paths and advertise the absolute
configured sitemap URL, which may later identify a sitemap index. Custom
rules are not accepted; manage specialized crawler policies at your host.
Generation uses normal ownership, collision checks, dry-run handling, caching,
and pruning. Disabling it removes its owned output on the next sitemap build.

Serve this file as **`https://your-host/robots.txt`**. When the site uses a
base path such as `https://your-host/blog`, deploy the site files under `/blog`
and separately copy or map the generated robots file to host-root `/robots.txt`.
Serving it only at `/blog/robots.txt` does not control host crawling. For shared
hosts, incorporate its Sitemap line into the host's existing robots.txt using
your deployment configuration. Preserve crawler access to public assets and
noindex pages. See [robots.txt placement](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt).

Optional `<modified>` records a trustworthy content modification date as
`YYYY-MM-DD` or an ISO timestamp with seconds and an explicit timezone
(`Z` or `±HH:MM`). It is never inferred from build time or file timestamps.
Unknown dates omit sitemap `lastmod`; malformed, duplicate, or nested fields
reject the article. Native sitemaps emit `<lastmod>`; XSLT sitemap input uses
`<url lastmod="...">absolute URL</url>` and omits the attribute when unknown.
The reference sitemap stylesheet handles both forms.

Set top-level `"sitemap": {"include_listings": true}` to include public index
and tag pages; the default is false. Global sitemap scope remains complete
under language, slug, and section filters. Listing pages omit modification
dates because their full content modification time is not known. See
[sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).

Article XML may specify `<indexing>noindex</indexing>` or
`<indexing>index</indexing>` (default when absent). Values are case-sensitive;
duplicate, nested, empty, and unknown directives reject the article. This
setting is independent of publication status: `unlisted` still publishes a
page and permits indexing by default, while excluding archive, feed, sitemap,
and search listings. Explicit translation groups are an exception: indexable
unlisted peers appear in reciprocal hreflang links on their translations.
Private and draft articles remain unpublished. A noindex page stays crawlable
and leaves the sitemap. Templates receive `articulous-indexing`; the reference
article template emits `<meta name="robots" content="noindex">` when requested.
Do not disallow noindex pages in robots.txt: crawlers need access to read the
directive. See [indexing controls](https://developers.google.com/search/docs/fundamentals/get-started-developers).

`tests/fixtures/site/xsl/pages/` contains reference templates for tests and
examples, not an installed production theme. Its HTML pages render meaningful
titles, resolved language, optional article descriptions, and one absolute
self-canonical URL. Index and tag inputs expose `@site`, `@lang`, and `@self`;
both expose `@page` and `@total`. Each pagination page uses its own
canonical URL. Relative-only builds omit canonicals. Adapt this contract in
your production templates; see [canonical URL guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls).

Index and tag inputs expose `@previous` and `@next` URLs, with empty strings at the
sequence boundaries. `IndexPage` and `TagPage` carry the same values as `previous_url` and
`next_url`. Render ordinary anchor links when nonempty, as in the
reference index template, so crawlers can reach every page from page one.
See [pagination guidance](https://developers.google.com/search/docs/specialty/ecommerce/pagination-and-incremental-page-loading).

Article stylesheets receive literal string parameters `articulous-url`
(resolved article URL), `articulous-lang` (validated language including fallback),
and `articulous-site` (configured site name). Declare each with a top-level
`<xsl:param name="articulous-url"/>` and read it as `$articulous-url`.
The contract works with lxml and SaxonC. Parameters participate in incremental
fingerprints; metadata-only configuration changes rebuild article pages.
The captured source XML and its original document base URI are preserved.
An empty site base URL produces root-relative article URLs; templates should
omit absolute canonical markup in that case. See the
[lxml parameter documentation](https://lxml.de/xpathxslt.html#stylesheets-parameters)
and [Saxon command-line parameters](https://www.saxonica.com/html/documentation12/using-xsl/commandline/index.html).

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
Per-task timings stay at DEBUG; use `--verbose` to inspect individual
transform durations. INFO logging avoids a timing line for every page.
Long article scans report cumulative scanned, parsed, and skipped counts
at INFO at most once every five seconds, after a file is parsed. Short
scans emit no progress lines. These are parsing counts: accepted private
articles count as parsed; publication exclusions appear in the final build
summary. Enable INFO logging to see progress when using a quieter log level.
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
| `sitemap`     | `include_listings` — include index/tag pages (boolean, default false) |
| `robots`      | `enabled` — generate host-root robots.txt alongside sitemap (boolean, default false) |
| `site`        | `site_name`, `base_url`, `languages`, `default_language`, `bare_default_language`, `pagination.per_page`, `pagination.rss_items`, `pagination.paginate_tags`, `pagination.empty_index` |
| `urls`        | URL patterns for `article`, `index`, `tag`, `rss`, `sitemap`, `search` (e.g. `/{lang}/articles/{slug}/`); optional `index_first` |
| `build`       | `cache_file`, `parallelism` (`"auto"` or a positive int), `force_full_build` (boolean)              |
| `logging`     | `level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), `file` (optional path)                       |

Tag pagination is opt-in: set `site.pagination.paginate_tags` to `true` after
adding previous/next links to your tag template. The default is `false`, preserving
one page per tag for existing sites. Enabled tags use `pagination.per_page`.
The configured `urls.tag` remains page one; later pages append `/page/2/`,
`/page/3/`, and so on. For example, `/en/tags/linux/` keeps its address and page
two is `/en/tags/linux/page/2/`. Paginated tags participate in incremental caching,
selected-language cleanup and the sitemap when `include_listings` is enabled.

Python consumers can call `build_tags_models(articles, lang, ctx, paginate=True)`
from `articulous.models`. Supply articles already sorted and filtered for
publication, with a validated positive `ctx.per_page`. For a global archive,
pass `lang=""` and an API context whose `url_patterns["tag"]` is `/tags/{tag}/`.
The CLI still uses its configured language-specific tag pattern.

`site.bare_default_language` lists the sections whose default-language pages
drop the `/{lang}/` segment of their pattern. With `["index", "tags"]`, the
default language's listings are written to `/page/2/` and `/tags/linux/` while
every other language keeps `/fr/page/2/` and `/fr/tags/linux/`, which matches
a site whose untranslated pages already live at bare routes. `articles`,
`index`, `tags` and `rss` (once `urls.rss` names `{lang}`) may be listed; each
listed section's pattern must contain a `/{lang}/` segment. The default is
`[]`, so existing sites keep their prefixed URLs. By default, page one of a bare
index is `/page/1/`.

Set `urls.index_first` to `"/{lang}/"` to make page one canonical at `/en/`,
`/fr/`, and so on. With `"index"` in `site.bare_default_language`, the default
language instead uses `/`. Later pages keep `urls.index`, and page two links
back to the canonical root. No numbered page-one alias or redirect is generated.
The default `index_first: null` preserves numbered page-one routes.
Set `site.pagination.empty_index` to `true` to render one empty index page for
each enabled language without published listing articles; the default is `false`.

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
`-ext:off`, `-xi:off` and `-config:<temporary-configuration.xml>` to disable
external functions, XInclude and external resource URIs. The configuration uses
`<global allowedProtocols="#none"/>` in the Saxon configuration namespace.
SaxonC-HE 12.10 passes all 16 native integration checks, including these
restrictions (see [native validation](reviews/saxonc/README.md)).
SaxonC requires standalone stylesheets: external includes and imports
are rejected. Use lxml for stylesheets with local includes or imports.
Planning captures stylesheet bytes and local dependencies; workers compile
that snapshot, so edits during execution apply on the next build. Fingerprints
include the captured bytes and logical file URIs. With lxml, relative includes
resolve beside the configured stylesheet path, including symlink paths;
`xml:base` applies consistently to both capture and compilation. Every dependency
must be a regular file and is opened without blocking on special files.
Captured article documents retain their effective base URI. SaxonC preserves
it by inserting or normalizing the root `xml:base` attribute in its temporary
XML input; stylesheets inspecting that attribute can observe this metadata.
The `"native"` engine is available only for `sitemap` and `search`; it
streams those standard formats with bounded memory. Select `lxml` or
`saxonc` for either section when custom XSLT output is required.

Native production builds automatically partition sitemaps at 50,000 URLs
or 50 MiB of uncompressed UTF-8 XML, including the document envelope.
A single shard stays at the configured sitemap path; multiple shards turn
that path into a sitemap index. Shard names include their sequence and content
fingerprint. New shards publish before the index, preserving the old index
and its referenced files if publication fails. Successful builds prune retired
owned shards, including when the sitemap shrinks back to one file. Interrupted
builds require a full recovery build under the existing ownership rules.
The low-level `build_sitemap_section` caller must provide a `TempWorkspace`
for automatic partitioning and retain it until its returned tasks finish;
without a workspace it remains a single-file writer with strict limits.

Configuration loading validates `site.base_url` for every backend. Supported
forms are an absolute HTTP(S) URL, an empty string, or a root-relative prefix
such as `/blog`. A value such as `not-a-url`, a protocol-relative host such as
`//example.com`, invalid ports/escapes, and query or fragment delimiters are
rejected with a `site.base_url` error. Base paths must be URI-encoded and
cannot contain dot segments, repeated internal separators, or credentials.

When the native sitemap is selected, `site.base_url` must be an absolute
HTTP(S) URL, such as `https://example.com` or `https://example.com/blog`.
Use URI-encoded base paths, without credentials, queries, or fragments.
An empty base still produces relative links in builds excluding the native
sitemap, for example `--only articles,index,tags,search`. Custom XSLT outputs
remain the stylesheet author's responsibility.

Native sitemap planning checks each location: it must be URI-encoded,
shorter than 2,048 characters, and inside the sitemap's host and directory.
Dot segments and repeated path separators are rejected. For example,
`/feeds/sitemap.xml` cannot list `/en/articles/post/`; put the sitemap at
`/sitemap.xml` to cover both language trees. These checks follow the
[Sitemaps protocol](https://www.sitemaps.org/protocol.html).
Production builds partition oversized URL sets. Each shard and the sitemap
index retain the 50,000-entry and 50 MiB uncompressed XML limits; an entry
that cannot fit in one shard fails before publication.

Placeholders use plain names; attribute/index traversal, conversions and nonempty
format specifications are rejected before any expansion. Formatting widths cannot
allocate a generated path during configuration admission.

URL patterns are validated by section:

| URL key   | Required placeholders | Output shape |
| --------- | --------------------- | ------------ |
| `article` | `{lang}`, `{slug}`    | Directory-style; `index.html` is appended |
| `index`   | `{lang}`, `{page}`    | Directory-style; `index.html` is appended |
| `index_first` | `{lang}` only, when non-null | First index page; must end with `/`; `index.html` is appended |
| `tag`     | `{lang}`, `{tag}`     | Directory-style; `index.html` is appended |
| `rss`     | none                  | File-style path, such as `/rss.xml` |
| `sitemap` | none                  | File-style path, such as `/sitemap.xml` |
| `search`  | none                  | File-style path, such as `/search.json` |

When `site.bare_default_language` names a section, the default language uses
that pattern without its `/{lang}/` segment; the pattern itself is validated as
written above.

Directory-style patterns must not end in a file suffix. File-style
patterns must include one and must not end with a slash. Patterns are
local paths: schemes, hosts, query strings, fragments, percent escapes,
backslashes, and control characters are rejected before a build starts.
Generated paths and their components are checked against the target
filesystem's byte limits during planning, before assets or pages are
published. Oversized slugs or tags fail the build; they are not truncated.

Route literals containing spaces or Unicode are percent-encoded in links
while keeping their original filesystem names. With base
`https://example.com/blog` and article pattern `/café/{lang}/{slug}/`,
`output/café/en/post/index.html` is served at
`https://example.com/blog/caf%C3%A9/en/post/`. Configure the web server to
mount the output directory at `/blog/`; the deployment prefix is not an
extra directory inside `output/`.

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

The CLI and `run_build` replace generated pages and feeds individually and
atomically; their whole build is not transactional. A live generated target or
any parent component that is a symlink is rejected. Content writes use the original staging file
descriptor; SaxonC inherits that descriptor through `/dev/fd`. A replaced
staging entry is rejected before publication. Publication and temporary-file
cleanup stay anchored to the original destination directory. A directory replacement
detected after rendering aborts publication; cleanup and permission changes
use the original directory and file descriptors.
Before publishing, the ownership file records
all previously owned and planned paths. Interrupted builds retain this
record, including old paths from failed URL changes. Retry without
`--only`, `--lang` or `--slug`: recovery forces a full rebuild and prunes
obsolete paths, then clears the recovery flag. A dry run leaves that flag
intact. Cache-write failures also retain the recovery flag, so the next
unfiltered build cannot reuse fingerprints from an older publication.
Inspect partial output before deploying after a failed build.
Existing unowned targets enter recovery ownership only after publication
replaces them; a planned target that was never replaced is preserved.

Route changes can replace a selected obsolete file with a directory, or a
directory of selected obsolete files with one file. Planning checks ownership
before publication; `--dry-run` reports these removals without changing output.
Retained outputs, unowned files, extra empty directories and unsafe file types
block the migration. The recovery journal is saved before removing obstructions,
so an interrupted migration can be retried or reverted with a full build.

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
destination symlinks and hardlinks are rejected. Asset source opens reject
symlinks in every path component. Each asset file is copied through open
file descriptors and replaced atomically; the complete mirror is not
transactional. For predictable pruning, reserve the output tree for generated
files and avoid adding symlinks inside it.
Pruning removes stale generated symlinks themselves, preserving their
targets. A symlink in a stale path's parent directories aborts pruning.
Outside a planned route migration, if a stale owned file has become a directory,
pruning stops and preserves
the directory and its contents. Move or remove it explicitly before retrying;
page/feed ownership never authorizes recursive directory deletion.
Cached generated outputs must remain regular files. A directory, FIFO, or
device in place of a cached page/feed stops both normal and forced builds;
the entry is preserved for explicit recovery. Remove or relocate it, then
retry. A missing generated file is rebuilt automatically.

For validation before publication, use `check_build` or the
`prepare_build` → `render_prepared` → `validate_generated` Python lifecycle.
These APIs capture inputs and render a fresh isolated tree; `check_build`
leaves the published output, fingerprint cache and ownership state unchanged.
`build_site` additionally publishes a validated generation through the Linux
backend, with exception rollback and a recovery journal covering output and
build state. Its two directory renames leave a brief gap in output visibility;
it does not promise atomic whole-site visibility or power-loss durability.
Windows and macOS publication backends remain unsupported/unvalidated.
See the [composition and publication guide](docs/generator-composition.md)
for extra pages, validator hooks, capability checks and recovery instructions.

---

## 🧪 Development

The [composition and publication guide](docs/generator-composition.md) documents
implemented route, page, validation and publication APIs and their regression
coverage. Remaining decisions and declined work are tracked in [TODO.md](TODO.md).

The package is covered by a pytest suite with fixture‑based site builds,
unit tests, and section‑order fuzz tests. Rendered fixture feeds are checked
for required RSS channel metadata, namespaced sitemap structure with both
native and lxml backends, and links to generated HTML pages. The RSS fixture
uses the test site's English first index page as its channel website.
Coverage is enforced at
**100 % line + branch** via `pytest-cov` (`--cov-fail-under=100`).
The subsequent native per-function gate independently inventories source, rejects
stale or inconsistent counters, and requires at least 80% executable lines for
each function. Empty protocol declarations must have genuinely empty native
regions; executable functions cannot substitute empty counters.

Seeded fuzz tests mutate configuration types and URL syntax, duplicate XML
metadata, and out-of-range dates. Boundary probes cover numeric minima,
platform-sized integers, URL lengths, ports, sitemap resource budgets, and
the target filesystem's byte limits. Valid boundary cases prevent excessive
rejection; failing builds must preserve published outputs and cache state.
Seeds are fixed for reproducibility.

The tests use lxml for XML validation; `xmllint` is not required. Native JavaScript
tests require Node 24 and an installed Chromium executable. The browser test uses
`ARTICULOUS_CHROMIUM`, or finds `chromium`/`google-chrome` on PATH; missing native
tools fail acceptance. In an activated virtual environment, install the test
extra and run:

```sh
python -m pip install -e ".[test]"
python -m pytest
python -m articulous.coverage_gate coverage.json --directory articulous
ruff check --no-cache .
ruff check --no-cache --select C901 --config 'lint.mccabe.max-complexity = 9' articulous tests
PYRIGHT_PYTHON_IGNORE_WARNINGS=1 pyright --pythonpath .venv/bin/python
```

CI runs only on manual dispatch. In GitHub Actions, select
**Test Articulous Generator** and choose **Run workflow**.

For offline checks, reuse installed dependencies and skip installation commands.
`PYRIGHT_PYTHON_IGNORE_WARNINGS=1` disables the Python launcher's registry query
for update warnings; use its already installed bundled engine. Do not request
`latest` or install missing tools on a metered connection without authorization.
The native JavaScript coverage gate uses the installed Acorn 8.17.0 parser.
Set `ARTICULOUS_ACORN` to its package directory when it is outside the normal
Node lookup path, for example the existing local cache:

```sh
export ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn
export ARTICULOUS_CHROMIUM=/home/netto/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell
```

`tests/test_code_browser.py` runs the maintained code adapter and copy plugin in
native Chromium against a loopback fixture. It checks DOM/controller lifetimes,
clipboard failures and stale callbacks, and requires >=80% native executable-line
coverage for every function. Clipboard calls use controlled promises; the test
does not write to the system clipboard. See the [recorded browser evidence](reviews/browser/README.md).
The test never downloads a browser; manual CI uses its runner's installed Chrome.

`package-lock.json` pins that verification dependency for manual CI runs.
The parser and test commands never install it automatically; CI's explicit
`npm ci --ignore-scripts --no-audit --no-fund` step requires network access unless
its dependency is already cached. No local installation is needed to reuse the
cache above.

CI installs the versions in `uv.lock` with
`uv sync --locked --extra test --no-build --no-install-project` for each
Python version. To use those locked dependencies locally, run that
command with `--python 3.11` (or another CI version), then use the tools
in `.venv/bin/`. The CI job runs Ruff, Pyright and pytest; the separate
`C901` command above provides a supplementary complexity check. Every new or
changed function requires cyclomatic complexity <=9 without exemptions, measured
by SonarQube or an equivalent installed local analyzer. Record analyzer/version,
counting conventions, supported syntax and per-function results; validate analyzer
gaps rather than treating missing results as passes. Unsupported syntax fails
acceptance rather than receiving an estimated or missing score.
The [offline complexity workflow](reviews/complexity/README.md) records calibrated
Lizard/ESLint and native XPath/XSLT measurements in one source-bound report.
`python -m articulous.complexity_gate check` validates every language component
without downloads; CI enforces this aggregate check.

A separate Linux integration job downloads the
[SaxonC-HE 12.10 executable](https://downloads.saxonica.com/SaxonC/HE/12/index.html),
verifies its pinned SHA-256 checksum, and runs all six sections with the real
backend. It also checks cache reuse, blocked file/HTTP reads and external
entities, disabled XInclude expansion and secondary writes, and preservation
of previous output when compilation or execution fails. The ordinary suite
keeps fast mocked subprocess tests and skips these integration checks unless
`ARTICULOUS_SAXONC_HOME` is set. A configured but unavailable executable fails
the integration checks rather than falling back to lxml.

To reproduce with the extracted Linux 12.10 archive:

```sh
saxonc_root=/path/to/SaxonCHE-linux-x86_64-12-10-0
ARTICULOUS_SAXONC_HOME="$saxonc_root/SaxonCHE" \
LD_LIBRARY_PATH="$saxonc_root/SaxonCCoreHE/lib:$saxonc_root/SaxonCHE/lib" \
.venv/bin/pytest --no-cov tests/test_saxonc_integration.py
```

---

## 📜 License

MIT
