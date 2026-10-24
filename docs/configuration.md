# Configuration

[Documentation](../README.md#documentation)

Configuration lives in `config.json`. If the file is missing, defaults
are written automatically on first run. Malformed existing configuration
fails fast instead of being overwritten.
Supplied JSON is merged with defaults, so omitted settings use their
defaults. Unknown keys and invalid value types are rejected.

| Block | Keys |
|---|---|
| `paths` | `content_dir`, `output_dir`, `xsl_dir`, `assets_dir` |
| `engines` | per‑section engine (`articles`, `index`, `tags`, `rss`, `sitemap`, `search`) → `"lxml"` or `"saxonc"`; `"native"` also supported for `sitemap` and `search` (their default) |
| `saxonc` | `home` — path to the SaxonC install (optional; `Transform` is discovered on `PATH` when null) |
| `sitemap` | `include_listings` — include index/tag pages (boolean, default false) |
| `robots` | `enabled` — generate host-root robots.txt alongside sitemap (boolean, default false) |
| `site` | `site_name`, `base_url`, `languages`, `default_language`, `bare_default_language`, `pagination.per_page`, `pagination.rss_items`, `pagination.paginate_tags`, `pagination.empty_index` |
| `urls` | URL patterns for `article`, `index`, `tag`, `rss`, `sitemap`, `search` (e.g. `/{lang}/articles/{slug}/`); optional `index_first` |
| `build` | `cache_file`, `parallelism` (`"auto"` or a positive int), `force_full_build` (boolean) |
| `logging` | `level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), `file` (optional path) |

## Languages and pagination

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

## Site address

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

## URL patterns

Placeholders use plain names; attribute/index traversal, conversions and nonempty
format specifications are rejected before any expansion. Formatting widths cannot
allocate a generated path during configuration admission.

URL patterns are validated by section:

| URL key | Required placeholders | Output shape |
|---|---|---|
| `article` | `{lang}`, `{slug}` | Directory-style; `index.html` is appended |
| `index` | `{lang}`, `{page}` | Directory-style; `index.html` is appended |
| `index_first` | `{lang}` only, when non-null | First index page; must end with `/`; `index.html` is appended |
| `tag` | `{lang}`, `{tag}` | Directory-style; `index.html` is appended |
| `rss` | none | File-style path, such as `/rss.xml` |
| `sitemap` | none | File-style path, such as `/sitemap.xml` |
| `search` | none | File-style path, such as `/search.json` |

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

RSS optionally accepts `{lang}` to create one feed per language; omitting it
keeps a shared feed. See [engines](engines.md) for engine selection and worker
counts, and [search discovery](search-discovery.md) for sitemap limits and robots
rules. Path and state-file safety rules are in [output and ownership](output.md).
