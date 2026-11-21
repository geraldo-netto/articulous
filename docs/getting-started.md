# Getting started

[Documentation](../README.md#documentation)

Install Articulous, prepare a site folder, then run the first build.

## Install and run

Requires Python 3.11 or newer and a Unix platform with `fcntl` file
locking. CI runs on Ubuntu with Python 3.11–3.14. Native Windows execution
is not supported by the current filesystem layer.
The supervised SaxonC runner and optional whole-site publisher require Linux;
their native Windows and macOS backends are unsupported.

From a repository checkout, install the package in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Create a site with the [source directories and templates](#site-layout),
then run from that site's root using the installed command:

```sh
articulous
```

You can also run the installed package as a module:

```sh
python -m articulous
```

Both entry points use the current working directory as the project
root. This repository includes a test site under `tests/fixtures/site/`;
the repository root itself does not contain production content/templates.

## Site layout

A site directory contains its data and templates:

```
your-site/
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
│       ├── sitemap.xsl     # only for custom XSLT sitemap output
│       └── search.xsl      # only for custom XSLT search output
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

Continue with [building and recovery](building.md). Configure names and paths in
[configuration](configuration.md); keep generated files as described in
[output and ownership](output.md).
