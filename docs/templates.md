# Templates

[Documentation](../README.md#documentation)

Templates control the generated HTML and feed content. The fixture templates
illustrate the contract; they are not a packaged production theme.

## Required files

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

## Page inputs

[The reference templates](../tests/fixtures/site/xsl/pages/) are test/example
templates, not an installed production theme. Their HTML pages render meaningful
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

## Structured-data rendering

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

## Translation links

Templates receive `articulous-translation` and `articulous-alternates`.
The latter is a pre-escaped HTML fragment of self-inclusive reciprocal
`<link rel="alternate" hreflang="..." href="..."/>` elements, sorted by locale.
Emit it in the head with `<xsl:value-of select="$articulous-alternates"
disable-output-escaping="yes"/>`, as in the reference template. Relative-only
builds omit the fragment. Metadata fingerprints track peer URLs and membership.

See [articles](articles.md) for accepted metadata, [configuration](configuration.md)
for routing and pagination, and [engines](engines.md) for execution restrictions.
