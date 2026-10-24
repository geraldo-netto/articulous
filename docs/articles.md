# Articles

[Documentation](../README.md#documentation)

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

## Field and publication rules

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

## Content modification

Optional `<modified>` records a trustworthy content modification date as
`YYYY-MM-DD` or an ISO timestamp with seconds and an explicit timezone
(`Z` or `±HH:MM`). It is never inferred from build time or file timestamps.
Unknown dates omit sitemap `lastmod`; malformed, duplicate, or nested fields
reject the article. See [sitemap contents](search-discovery.md#sitemap-contents)
for output metadata.

## Indexing

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

## Structured data

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

After adapting and deploying your template, run its public article URL through
Google's [Rich Results Test](https://search.google.com/test/rich-results), or paste
the generated HTML into its code input. Confirm the intended Article/BlogPosting
item, canonical URL, author/image, and dates; investigate errors and relevant
warnings. This repository's tests parse rendered JSON-LD locally; the external
Rich Results Test remains a deployment check.

## Translations

Use the same `<translation>story-id</translation>` in articles that are actual
translations. IDs contain 1–128 ASCII letters/digits with hyphen or underscore
separators; duplicates within one article, malformed IDs, and nested fields
reject that article. There can be only one indexable page per translation ID
and normalized locale; ambiguity fails before publication. Relationships are
never inferred from titles or slugs. Private, draft, and noindex peers are
excluded; unlisted peers remain indexable by default.

Annotation locales use ISO language, optional script, and optional region codes
(for example `en`, `en-US`, `zh-Hant-TW`); `en_US` normalizes to `en-US` without
changing the route. Unsupported codes fail translated builds. Bundled identifiers
come from the [IANA registry](https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry)
and ISO 3166-1 alpha-2; numeric and reserved regions such as `419`, `EU`, and `UK`
are excluded, following [hreflang guidance](https://developers.google.com/search/docs/specialty/international/localized-versions).
Filtered builds still discover all peers. If a filter would leave an unselected
peer with stale reciprocal links, the build fails before publishing; run a full
build after relationship changes. Unchanged groups support targeted builds.

For rendering parameters, see [templates](templates.md). For crawler rules, see
[search discovery](search-discovery.md).
