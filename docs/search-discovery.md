# Search discovery and feeds

[Documentation](../README.md#documentation)

Configure how crawlers and feed readers discover published content. Article
publication and indexing rules are in [articles](articles.md).

## robots.txt

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

## Sitemap contents

Set top-level `"sitemap": {"include_listings": true}` to include public index
and tag pages; the default is false. Global sitemap scope remains complete
under language, slug, and section filters. Listing pages omit modification
dates because their full content modification time is not known. See
[sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).

The optional [article modification date](articles.md#content-modification)
supplies sitemap metadata; unknown dates omit `lastmod`. Native sitemaps emit
`<lastmod>`; XSLT sitemap input uses
`<url lastmod="...">absolute URL</url>` and omits the attribute when unknown.
The reference sitemap stylesheet handles both forms.

## Native sitemap limits

Native sitemap planning checks each location: it must be URI-encoded,
shorter than 2,048 characters, and inside the sitemap's host and directory.
Dot segments and repeated path separators are rejected. For example,
`/feeds/sitemap.xml` cannot list `/en/articles/post/`; put the sitemap at
`/sitemap.xml` to cover both language trees. These checks follow the
[Sitemaps protocol](https://www.sitemaps.org/protocol.html).

## Sitemap partitioning

Native production builds automatically partition sitemaps at 50,000 URLs
or 50 MiB of uncompressed UTF-8 XML, including the document envelope.
The sitemap index has the same limits. An entry that cannot fit in one shard
fails before publication.
A single shard stays at the configured sitemap path; multiple shards turn
that path into a sitemap index. Shard names include their sequence and content
fingerprint. New shards publish before the index, preserving the old index
and its referenced files if publication fails. Successful builds prune retired
owned shards, including when the sitemap shrinks back to one file. Interrupted
builds require a full recovery build under the existing ownership rules.

### Low-level sitemap API

The `build_sitemap_section` caller must provide a `TempWorkspace`
for automatic partitioning and retain it until its returned tasks finish;
without a workspace it remains a single-file writer with strict limits.

## RSS feeds

`site.pagination.rss_items` controls the feed size; zero produces an empty feed.
The default `/rss.xml` is shared across languages. Set `urls.rss` to a file-style
pattern containing `{lang}` for one feed per language. The configured language
and slug filters do not narrow a selected global feed.

See [configuration](configuration.md) for URL patterns and [templates](templates.md)
for custom RSS/sitemap output. For a partial sitemap rebuild, use
[the build guide](building.md#build-part-of-a-site).
