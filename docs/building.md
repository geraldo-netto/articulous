# Build and recover a site

[Documentation](../README.md#documentation)

Articulous turns your article files, templates and assets into website files.
The result goes into `output/` unless your configuration selects another folder.
Building locally does not upload or deploy the site.

## Before you start

You need an installed copy of Articulous and a site folder containing its
configuration, articles and XSL templates. See the
[getting-started guide](getting-started.md) for installation and the required folder layout.
The repository's `tests/fixtures/site/` folder is a small example, not a complete
website theme.

Run commands from your site's root folder. Selecting another configuration with
`--config` does not change that root. Activate the Python environment in which
Articulous is installed before using the commands below.

If your site supplies its own build command, use that command. It may add custom
pages or files that the standard `articulous` command does not declare.

## Check and build

First, inspect the planned work:

```sh
articulous --dry-run
```

A dry run checks paths and inputs without publishing website files or saving the
build cache. It can create a missing configuration, lock files, temporary files
and a configured log. It does not render every page or check every generated
link.

To build all sections:

```sh
articulous
```

Unchanged generated files may be reused. To rebuild selected output regardless
of cached fingerprints:

```sh
articulous --force
```

Keep files you want published in the source folders. Manual additions under
`output/assets/` are removed by the asset mirror. Removing a source asset also
removes its generated copy; a missing source assets folder removes the mirrored
assets tree.

## Build part of a site

Article pages hold individual posts. Index and tag pages group posts. RSS serves
feed readers, sitemaps list pages for search engines, and search data supports the
site's search feature.

For example, rebuild only the sitemap:

```sh
articulous --only sitemap
```

Other examples:

```sh
articulous --only index,tags
articulous --lang en
articulous --slug hello-world
```

Section names are `articles`, `index`, `tags`, `rss`, `sitemap` and `search`.
`--lang` limits article and listing languages. `--slug` limits article pages;
listings and selected feeds still use complete eligible inputs. Selected
cross-language outputs remain complete. Assets are mirrored on every non-dry
build. `--force` keeps any filters you supplied.

For sites that declare custom pages through the Python API, omitted custom pages
remain during partial builds. A sitemap rebuild retains their saved inclusion
rules, including exclusions. A full build without those declarations removes
the old custom pages. If the saved rules are unavailable, sitemap planning stops
and requires a full build with the site's declarations.

## Command options

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

The installed command, `python -m articulous` and the checkout shim accept the
same options. For example:

```sh
articulous --only articles
articulous --only index,tags --verbose
articulous --lang en --lang fr --slug hello-world
articulous --config settings/site.json --dry-run
```

## Logging and planning checks

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

## Understand the supporting files

With the default output folder, Articulous uses these paths:

| Path | Purpose | How to handle it |
|------|---------|------------------|
| `.build-cache.json` | Remembers input fingerprints to avoid unnecessary rendering. | Losing it can make builds slower; ownership history is stored separately. |
| `.output.articulous-ownership.json` | Records which output files Articulous owns and their route details. | Keep it. If damaged or missing for an existing site, restore it or choose an empty output folder. |
| `.output.articulous.lock` and `..build-cache.json.articulous.lock` | Prevent cooperating builds from using the same output or cache simultaneously. | Files may remain after a successful build; their presence alone does not mean a build is running. |
| `.output.articulous-transaction/` | Holds recovery data for the optional whole-site publisher. | Reserved for Articulous. Do not use it for configuration, logs, caches or sources. |

Output folder names and cache settings can change these names. Only the filename
part of `build.cache_file` is used, under the project root.

The output root and its parent paths must not be symbolic links. Configured
source and output folders must stay inside the project root. Output must stay
separate from every source folder, and configuration must stay outside output.
Logs, cache, lock and ownership files must stay separate from configuration and
the source/output trees. A rejected path is a reason to fix the configuration or
inspect the files, not to bypass the check.

## Recover after a failure

Use the recovery path that matches the failed operation:

| Failed operation | Next action |
|------------------|-------------|
| Standard CLI build | Correct the reported cause, then run the site's complete build without section, language or slug filters. Interrupted ownership state forces rebuilding and removes obsolete owned output. A dry run does not clear that state. |
| Optional whole-site publication | Rerun the same publishing application with the same output and cache settings. `build_site` performs journal recovery before preparing a new generation. A standard CLI build does not consume this journal. |
| Native command reports `NativeCleanupError` or manual recovery | Keep the named files and directories. Native work may still own them. Ask the application maintainer to establish process shutdown and recover the recorded reservation before removing or reusing them. |

The standard CLI replaces files individually. A failed build can leave a mixture
of old and new output, so inspect the result before deploying it.

The optional whole-site publisher provides rollback and journal recovery on
Linux. Its directory replacement has a brief visibility gap; it does not promise
uninterrupted whole-site visibility or protection against sudden power loss.
Malformed recovery records and changed file identities require inspection.
Deleting recovery data to silence an error can remove the evidence needed to
restore the site.

## Validate a completed build

A dry run is a planning check. Applications that need checks on rendered files
can use `check_build` or the staged build API before publication. They can supply
checks for HTML, links, preferred page addresses (canonical URLs), search data
and sitemaps.

The optional site validator follows local links with a full site address such as
`https://example.com/blog`, a local prefix such as `/blog`, or an empty base
address. An anchor identifies a location within a page, such as
`#contact`. After a redirect, a target anchor replaces the incoming one, an
omitted anchor inherits it, and a trailing `#` clears it. The check uses redirect
rules supplied by the application without contacting a web server. Remote links
are outside this local-file check.

Site owners can ask their application's maintainer which checks are enabled.
Using a validation API without adding theme-specific validators does not imply
every page or link has been checked.

For extension and recovery code, see the
[Python integration guide](generator-composition.md). Maintainers can consult
the [review-fix verification record](../reviews/correctness/README.md).
