# Generator composition and publication

Articulous owns route planning, model projection, caching, rendering and local
publication. Callers supply site-specific content loaders, XML schemas, themes,
validators and hosting rules. The APIs below implement ARCH-002 through ARCH-005;
the earlier ARCH-001 assessment is preserved in Git history.

## Index options

The defaults remain numbered index pages and no page for an empty language.
Opt in through configuration:

```json
{
  "urls": {"index_first": "/{lang}/"},
  "site": {
    "bare_default_language": ["index"],
    "pagination": {"empty_index": true}
  }
}
```

Merge this fragment with the rest of the site's configuration. With English as
its default language, the site generates `/` and `/fr/` for page one; later pages
retain the configured `urls.index`, normally `/page/2/` and `/fr/page/2/`.
Page two links back to the canonical root. No numbered page-one alias or redirect
is emitted in this mode. `index_first` must be a local directory pattern ending
in `/`, with plain `{lang}` placeholders and no other fields.

The public model equivalent is
`build_index_models(articles, lang, ctx, options=IndexOptions(first_pattern="/{lang}/", include_empty=True))`
from [`articulous.models`](../articulous/models.py). Omitting `options` uses
`ctx.index_options` when present, otherwise the default `IndexOptions()`.
Inputs must already be publication-filtered, language-filtered and sorted newest
first. The collection supplies its length and supports iteration; pages consume
it in bounded batches. The builder rejects disabled languages and nonpositive
or boolean page sizes. Empty enabled languages produce `page=total_pages=1`,
no articles and empty previous/next URLs when `include_empty` is enabled.

## Composed routes and extra pages

[`articulous.composition`](../articulous/composition.py) exposes immutable
`Route` and `ExtraPage` values. A route has a stable `key`, `section`, canonical
`url`, relative POSIX `output_path`, optional `language`, `category` and boolean
`sitemap` eligibility. Extra pages require section `pages` and a `page:` key.
Their canonical URL must agree with the output path and configured base URL,
including its deployment prefix and URI encoding.

Sitemap categories are independent of route discovery:

| Category | Inclusion when `sitemap=True` |
| --- | --- |
| `article` | Included; built-in routes retain article indexing eligibility |
| `static` | Included regardless of the listings toggle |
| `listing` | Included only when `sitemap.include_listings` is true |
| `excluded` | Never included |

An `ExtraPage` supplies XML `model` bytes, a `stylesheet` path, `engine` (`lxml`
or `saxonc`, default `lxml`) and `role` (`page` or `not-found`, default `page`).
Stylesheets and their dependencies use the existing captured transformation
pipeline. SaxonC uses the configured executable and existing fallback behavior.
A not-found page must have category `excluded`; its filename, language, HTML
`noindex` and actual HTTP 404 hosting behavior remain caller responsibilities.

Initialize a caller using the same configuration normalization as the CLI:

```python
from pathlib import Path
from articulous.cli import CliOptions, parse_cli_args
from articulous.config import apply_cli_overrides, load_or_create_config

root = Path(".").resolve()
cli = CliOptions(parse_cli_args([]))
config = load_or_create_config(root / "config.json")
apply_cli_overrides(config, cli, root)
```

For a site with an `xsl/pages/about.xsl` template accepting `<about>`:

```python
from articulous.composition import ExtraPage, Route, RouteCatalog
from articulous.pipeline import run_build

about = ExtraPage(
    route=Route(
        key="page:about", section="pages",
        url=config["site"]["base_url"].rstrip("/") + "/about/",
        output_path="about/index.html", category="static",
    ),
    model=b"<about><title>About this site</title></about>",
    stylesheet=root / "xsl/pages/about.xsl",
)
with RouteCatalog() as routes:
    run_build(cli, config, root, extra_pages=[about], route_catalog=routes)
    for route in routes:
        print(route.key, route.url, route.output_path)
```

Use a fresh catalog for each build. It stores routes on disk and is re-iterable
until its context closes. It includes planned generated files, cached outputs
and retained ownership from partial builds; mirrored assets are not routes.
Discovery does not scan rendered HTML or depend on sitemap inclusion. Set
`cli.dry_run = True` to discover routes without rendering or publishing files.
Supply extra pages on each build that should generate them. They use the shared
collision checks, stylesheet/model fingerprints and output ownership machinery.
Duplicate keys, duplicate destinations, file/parent overlaps, path escapes and
the reserved `assets/` namespace fail during planning. Explicit extra pages are
planned even when built-in sections are filtered; `pages` is not a CLI `--only`
section. Native and XSLT sitemaps apply the same extra-page inclusion policy.

`build_tag_index_model(articles, lang, ctx)` returns a `TagIndex` containing
`TagSummary(tag, slug, count, url)` entries and a `to_xml()` method. Pass the same
sorted, eligible language collection used for tag archives. Repeated labels on
one article count once; distinct labels that normalize to the same slug fail.
Entries preserve first-seen order and use each archive's first-page URL. An empty
input produces an empty tag index. Construct an `ExtraPage` from its XML to render
it; the engine does not automatically choose a tag-index route or template.
Display labels, sidebar limits and sorting remain theme choices.

`catalogue.PublicationCatalogue(records, languages)` supplies a stable article
tuple and cached `tag_counts(language)` projections. It groups records by
language once, counts only listing-eligible records and returns immutable
`TagCount(slug, count, label)` values sorted by slug. Repeated normalized tags
count once per record; the first written label is retained. This metadata
contract preserves Morpha's C++/C# normalized-membership counts and does not
relax the separate archive-output collision checks. Empty enabled languages
have empty counts; disabled/invalid language identities are rejected.

Catalogue records are borrowed and must remain unchanged for its lifetime;
the engine's frozen `CapturedArticle` records satisfy this directly. Counts
are derived once and are not another mutable publication-state owner. Retained
storage is proportional to article references and unique language/tag pairs;
no DOMs or native handles are retained. Site adapters own display dates,
sidebar ordering/limits and XML conversion. Use the actual `RouteCatalog`
for known routes, independently of sitemap inclusion, rather than rerunning
tag pagination to discover links.

`composition.ExtraArtifact(output_path, bytes)` declares a non-page generated
file. Pass `extra_artifacts` to `run_build`, `prepare_build`, `check_build` or
`build_site`. Artifacts share regular output-path, ownership, collision,
fingerprint-cache and publication/recovery checks; they are excluded from
sitemaps. Their bytes are immutable caller inputs. HTML pages continue to use
the rendering pipeline through `ExtraPage` or built-in sections.

A `BuildComposition.artifacts` factory may derive these bytes from captured
articles and the planned page catalog. Its artifacts are registered before the
template-data factory runs, so templates see the complete catalog. Factories
are synchronous and may not mutate staged output. All declared artifact bytes
must be admitted/funded by the caller; failed planning/rendering/validation
publishes none of them. Engine ownership is authoritative: a site report is
metadata, not a second ownership marker. Hosting directives and deployment
rules remain caller policy; declaring `.htaccess` locally authorizes no remote
overwrite, removal or hosting change.

## Prepare, render and validate

Pass `composer=captured_site_callback` to `prepare_build`, `check_build` or
`build_site` to compose against the engine's article generation. The callback
receives the `extensions.CapturedSite` contract and returns `BuildComposition`:
an immutable extra-page tuple and an optional template-data factory. Iterate
`snapshot.articles(language=None)` for immutable `CapturedArticle` records,
newest first with stable discovery-order ties. Records own their XML bytes;
they do not expose spool paths. All publication policies use `captured_at`.
`invalid_articles` lets a caller reject parse failures before rendering.

The template factory receives that snapshot and the actual re-iterable route
catalog after all built-in/extra-page models are planned. It returns unique
`TemplateInput(relative_path, bytes)` values. Inputs are written into a private
stylesheet overlay, never project sources; unsafe paths/symlinks are rejected.
The engine then captures stylesheet dependencies and freezes their revisions.
This order supports route-aware generated includes without a second source scan,
dummy templates or inferring routes from a sitemap. External stylesheet resources
are captured at their existing logical locations rather than relocated.

The prepared context owns source spools, active readers, the route catalog,
overlay and captured engines. It closes readers before reclaiming their storage;
resuming a borrowed iterator after exit fails before another native read. A
retained article record remains valid because its bytes are owned. Template and
policy callbacks are synchronous trusted code, not sandboxed plugins. Exceptions,
invalid results and capture failures release their owned resources and do not
publish. Source/template storage scales with admitted content and generated
inputs; callbacks fund any records they retain and must not retain live handles
past context exit. These APIs do not promise an atomic snapshot of unrelated
source-tree files being edited by another writer.

[`articulous.builds`](../articulous/builds.py) exposes a context-managed whole-site
lifecycle. These APIs merge and validate a copy of the supplied configuration,
resolve paths against `project_root` and require an unfiltered build. They reject
`only_sections`, `only_langs` and `only_slugs`; incremental partial builds remain
available through `run_build`. Whole-site preparation always captures and renders
a fresh generation, regardless of `cli.dry_run` or fingerprint-cache hits.

```python
from articulous.builds import (
    Diagnostic, check_build, prepare_build, render_prepared, validate_generated,
)

def validate_about(staged):
    with staged.open_artifact("about/index.html") as source:
        if not source.read(4096).strip():
            return [Diagnostic("Empty about page", path="about/index.html")]
    return []

report = check_build(
    cli, config, root, extra_pages=[about], validators=[validate_about],
)
print(report.routes, report.diagnostics)

with prepare_build(cli, config, root, extra_pages=[about]) as prepared:
    staged = render_prepared(prepared)
    checked = validate_generated(staged, validators=[validate_about])
    print(checked.diagnostics)
```

`prepare_build` takes output/cache locks and captures article models, stylesheet
dependencies and assets. Its private stage sits beside the output directory;
callers do not provide a separate render target. Preparation does not publish the
site. `render_prepared` may run once per prepared build; it renders the captured
plan and fingerprints all staged file contents and directory paths. Source edits
after capture apply to the next build. The prepared context owns locks, the route
catalog and temporary resources; staged and validated handles expire when it exits.

`StagedBuild.routes` exposes the catalog and `open_artifact(relative)` opens a
regular file for streaming reads. Paths must stay inside the stage; absolute,
dot-segment, backslash and drive-style paths are rejected. Callers choose read
sizes. `validate_generated` verifies manifest targets, runs each validator and
checks the fingerprint again. A validator returns an iterable of `Diagnostic`
values or `None`; severity `error` rejects the build, while `warning` is retained
in the report. Exceptions and staged mutations also prevent publication.

Validators are trusted, read-only caller code. The engine does not sandbox them
or implement HTML/link/fragment/canonical/search checks for every theme. Provide
those checks through validators before publishing. `check_build` renders,
validates and discards its stage, leaving published output, cache and ownership
bytes unchanged. Lock files may remain after release. A changed staging-directory
identity is preserved for inspection instead of recursively deleting its replacement.

## Native publication boundary

[`articulous.publication`](../articulous/publication.py) provides shared
orchestration through the `PublicationBackend` protocol: `capabilities`, `locked`,
`recover` and `publish`. Native operations live in
[`backends/posix.py`](../articulous/backends/posix.py) and the existing
[`filesystem.py`](../articulous/filesystem.py) adapter primitives. Configuration,
route serialization, models and validation hooks remain shared.

Use `build_site` for the complete lifecycle, including recovery under locks
before preparation:

```python
from articulous.backends import publication_capabilities
from articulous.publication import build_site

print(publication_capabilities())
report = build_site(
    cli, config, root, extra_pages=[about], validators=[validate_about],
)
```

For explicit lifecycle control, select one backend and retain it throughout:

```python
from articulous.backends import get_publication_backend
from articulous.publication import publish_validated

backend = get_publication_backend()
with prepare_build(cli, config, root, extra_pages=[about], backend=backend) as prepared:
    checked = validate_generated(render_prepared(prepared), validators=[validate_about])
    publish_validated(checked, backend=backend)
```

Only Linux has an implemented, natively exercised publisher. Windows remains
unsupported; macOS native validation is unavailable, so its publisher is also
reported unavailable. Interface readiness does not establish native support.

| Capability | Linux publisher |
| --- | --- |
| Isolated staging and pre-publication validation | Supported |
| Exception rollback | Restores previous output, cache and ownership; failed rollback retains recovery data |
| Journal recovery after process interruption | Supported from publication journal creation onward |
| Atomic whole-site visibility | Unsupported: moving the old tree aside leaves a gap before installing the new tree |
| Power-loss durability | Unsupported: no durability claim for sudden power/storage failure |

`require_atomic=True` or `require_durable=True` rejects this backend before
staging in `build_site`; `publish_validated` also checks requested capabilities.
There is no silent fallback to weaker guarantees. Cache and output locks reject
concurrent cooperating builds, including builds sharing only one of those resources.

The publisher rejects unowned files and unexpected path types in an existing
output tree. The entire `assets/` subtree remains mirror-owned. Symlink targets,
changed directory identities and unsafe state files stop publication or recovery.
Output, fingerprint cache and ownership state are committed as one recoverable
generation. This does not make readers observe all three atomically, and callers
must keep other writers from modifying the output while a build is running.

The journal lives beside output at `.<output-name>.articulous-transaction/`.
Before the `committed` marker, recovery restores the previous generation (or
absence for an initial build); after it, recovery keeps the new generation and
finishes cleanup. Rename/state failures attempt rollback immediately. Failed
rollback retains backups and reports the journal location. A post-commit cleanup
failure logs `Publication committed; cleanup pending` and leaves publication
successful; recovery can finish that cleanup.

To recover explicitly, use the same resolved destination and cache paths:

```python
from articulous.publication import recover_publication

recover_publication(
    Path(config["paths"]["output_dir"]),
    root / Path(config["build"]["cache_file"]).name,
)
```

`build_site` performs this recovery automatically. Recover before resuming the
incremental CLI after interrupted whole-site publication; `run_build` retains its
own per-file ownership recovery and does not consume the directory journal.
Malformed journals or changed identities are preserved and require inspection;
do not delete the transaction backup to force a retry. A process killed before
journal creation may leave an unused private stage, but has not begun replacing
the published generation.

## Morpha integration decision

Morpha retains its content, localization choices, templates, concrete output
validators and hosting policy. Engine canonical roots, extra pages, route discovery,
validation hooks and local publication are available for an explicit migration.

Owner decision (2026-10-19): preserve Morpha's current portal-owned language
roots, numbered page-one redirect pages and `_redirects` rules during engine
integration. Register the roots as extra pages and the rule file as an auxiliary
artifact; keep the existing root/redirect/pagination regressions. Engine-owned
canonical roots remain an available opt-in capability for other callers. This
specific retained portal contract is the owner's explicit exception to its
general no-compatibility policy, not authorization for additional aliases.
Preserve the custom-404 directive and the separate live-hosting restrictions;
local rendering does not establish actual HTTP behavior.

## Verification

### Local size metrics

`articulous.image_optimization.optimize` is a separate, explicit maintenance
iterator. Supply an `image_contracts.ImageBackend`, roots, format choices and
size/quality thresholds. `backends.imagemagick.ImageMagick` adapts installed
`convert`, `identify` and optional `optipng`; no tool is downloaded. The iterator
owns one private scratch workspace until exhaustion/close. Consumers that can
stop early must close it, including on cancellation. Each conversion settles
before its result is yielded; apply mode atomically replaces a source only if
the result is smaller. Conversion/replacement failure leaves that source intact.
The source batch and largest selected image bound storage; caller owns admission
and returned `ImageResult` records. Native PNG dimensions and EXIF-oriented JPEG
rotation/format/metadata stripping are tested on Linux; other native platforms
have no validation claim. Missing executables remain visibly unavailable.

`articulous.output_metrics.scan(output, regions=(("header", "//header"),))`
returns an `OutputMetrics` mapping suitable for JSON serialization. The report
functions `overall`, `repeated_markup`, `class_weight` and `one_page` accept
caller-selected data/regions; site selectors and styling advice stay outside
the engine. Each HTML file is read/parsed once per scan. DOMs and page bytes
are released between files; retained size rows scale with page count and
counters with distinct extensions, sections, regions and class strings.
Callers own the returned mutable metrics. Empty trees and empty HTML are valid;
invalid XPath expressions fail without modifying artifacts. Gzip values are
local estimates, not measurements of HTTP encoding or transfers.

### Source editing

Source maintenance uses `articulous.source_files.replace_file(path, writer)`
and `articulous.source_transactions.source_transaction(root)`, independently
of generated-output publication. A transaction exposes `capture(relative)`,
`write(relative, bytes, force=False)` and its staged `stage` path. Supply
`final_paths=("manifest.json",)` when a caller's metadata must publish last;
the engine has no knowledge of an import manifest's schema or location.
`prefix` optionally selects the caller's temporary-directory label.

The context owns its private workspace and every staged file/backup until
commit or rollback settles. File streams close before replacement. Each
destination is checked against its captured hash before publication; paths
escaping the source root and symlink destinations are rejected. Existing
permissions survive replacement. Callers must exclude other writers that can
replace source directory identities during these operations; content checks
are not a native filesystem isolation mechanism. No process-crash or power-loss
atomicity is claimed for source edits.

Workspace identity is checked before publication and recursive cleanup.
Failed rollback retains its backups and names the workspace for caller-owned
recovery. A cleanup failure reports the retained path without reversing a
successful commit or masking the original error. Unknown replacement
workspaces are preserved. Storage is proportional to the selected source
batch and its previous contents; callers admit/fund that batch before editing.
Keep immutable historical sources and project-specific overwrite rules in
the calling importer. `tests/test_source_editing.py` retains boundary,
partial-failure, replacement-identity and recovery controls alongside the
callers' import/translation/taxonomy regressions.

Permanent regression coverage lives in `test_index_roots.py`,
`test_composition.py`, `test_prepared_build.py` and `test_publication.py`, alongside
the existing routing, sitemap, ownership, asset, lock and output-safety suites.
Coverage includes invalid/boundary inputs, cached/retained route discovery,
native/XSLT sitemap inclusion, source snapshots, validator failure/mutation,
output/cache contention, unsafe replacements, rollback failure and real process
termination at the prepared, old-moved, installed and committed journal phases.

Run `.venv/bin/pytest --cov-report=json:/tmp/articulous-coverage.json` for the
repository's 100% line/branch gate; inspect each production function's executable
line coverage against the 80% minimum. Pyright, Ruff and the C901 complexity check
remain required. Optional real-SaxonC tests require `ARTICULOUS_SAXONC_HOME`.
This evidence covers local Linux behavior, not Windows/macOS acceptance or
power-loss durability.

Morpha compatibility checks can be reproduced from its checkout with
`PYTHONPATH=.:tests .venv/bin/python -m unittest -q test_index_routes test_sitemap_listings test_validation test_tag_index test_not_found test_engine_contract`.
Those checks preserve existing portal behavior until its migration decision.
