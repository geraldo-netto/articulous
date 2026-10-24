# Articulous Static Site Generator

[![Articulous](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml/badge.svg)](https://github.com/geraldo-netto/articulous/actions/workflows/main.yml)

Articulous turns XML articles, XSLT templates and assets into website files.
It can render several pages at once and remembers earlier inputs to skip
unchanged work. It is written in Python, with lxml and optional SaxonC backends.

Start with [getting started](docs/getting-started.md), then use
[building and recovery](docs/building.md) for everyday commands.

## Documentation

| Guide | Use it to |
|-------|-----------|
| [Getting started](docs/getting-started.md) | Install Articulous and prepare a site folder. |
| [Building and recovery](docs/building.md) | Plan, build selected sections, inspect logs and recover after failure. |
| [Articles](docs/articles.md) | Write XML articles, set publication status and provide metadata. |
| [Templates](docs/templates.md) | Supply XSL templates and render metadata, pagination and translation links. |
| [Configuration](docs/configuration.md) | Set paths, languages, pagination and URL patterns. |
| [Rendering engines](docs/engines.md) | Choose lxml, SaxonC or native writers and understand their limits. |
| [Search discovery and feeds](docs/search-discovery.md) | Configure robots.txt, sitemaps and RSS feeds. |
| [Output and ownership](docs/output.md) | Understand generated files, asset mirroring, caches, locks and publication. |
| [Development and verification](docs/development.md) | Run tests, coverage, complexity and offline acceptance checks. |
| [Python integration](docs/generator-composition.md) | Compose custom pages, discover routes and validate or publish staged builds. |

## Capabilities

- Generates article pages, paginated indexes, tag pages, RSS, sitemaps and search data.
- Supports multiple languages, scheduled publication, dry runs and filtered builds.
- Provides extra-page, route-discovery and validation APIs, plus optional Linux
  whole-site publication with rollback and journal recovery.

Requirements and platform limits are in [getting started](docs/getting-started.md).
Open work and retained decisions are tracked in [TODO.md](TODO.md).

## License

[MIT](LICENSE).
