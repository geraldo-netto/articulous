# Generator composition and publication

[Documentation](../README.md#documentation)

Articulous owns route planning, model projection, caching, rendering and local
publication. Callers supply site-specific content loaders, XML schemas, themes,
validators and hosting rules. This is the developer reference for composing a
build. For everyday commands and failure recovery, start with the
[build and recovery guide](building.md).

## Index options

Public build entry points accept the independent `BuildOptions` interface and
`ConfigurationInput` mapping, then normalize a private copy through one adapter.
For callers without a CLI:

```python
from articulous.configuration_contracts import BuildRequest
from articulous.builds import check_build

report = check_build(BuildRequest(), {}, root)
```

`BuildRequest` validates boolean flags, copies/deduplicates selection sequences
into immutable tuples, and carries a `Path` for configuration identity. Empty
selections remain unfiltered. `SiteConfiguration` composes independent typed
blocks; their required keys define validation regardless of implementation
defaults. Malformed schema values raise `ConfigurationError` (a `ValueError`).
`ConfigurationOptions` narrows the view needed by JSON/CLI path adapters. CLI
parsing converts through `CliOptions.as_request`; it defines no core schema.
Partial configuration mappings merge with defaults without mutating the caller.
`admit_configuration` projects types only after complete schema validation;
`normalize_configuration` additionally validates paths and applies request flags.

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

[`articulous.composition_contracts`](../articulous/composition_contracts.py) defines immutable
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
from articulous.composition_contracts import ExtraPage, Route
from articulous.composition import RouteCatalog
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

Use a fresh catalog for each build. The SQLite adapter implements independent
`RouteReader`/`RouteWriter` interfaces. It stores routes on disk and is re-iterable
until its context closes. Each admitted cursor belongs to the catalog; iterator
exit releases it and catalog close settles all remaining readers before closing
the connection. Resuming a reader after cutoff raises before a native read.
Initialization and cursor-admission failures close their new resources. Callers
retain the catalog for retry if a native close raises. It includes planned generated files, cached outputs
and retained ownership from partial builds; mirrored assets are not routes.
Discovery does not scan rendered HTML or depend on sitemap inclusion. Set
`cli.dry_run = True` to discover routes without rendering or publishing files.
Supply extra pages on each build that should generate them. They use the shared
collision checks, stylesheet/model fingerprints and output ownership machinery.
Route metadata is persisted with ownership independently of fingerprint caches,
so partial discovery preserves exact canonical URLs, languages and sitemap
eligibility after cache loss or replacement. Legacy ownership can recover known
metadata from its cache once. If both sources lack a retained route's semantics,
discovery requires a full build rather than inventing metadata. A partial build
without discovery can retain those files while leaving their metadata unknown.

Index and tag routes preserve the model's exact canonical URL, including its
choice of a trailing slash, first-index override and paginated tag URL. Discovery
does not reconstruct those canonical URLs from output filenames.

Duplicate keys, duplicate destinations, file/parent overlaps, path escapes and
the reserved `assets/` namespace fail during planning. Explicit extra pages are
planned even when built-in sections are filtered; `pages` is not a CLI `--only`
section. Native and XSLT sitemaps apply the same extra-page inclusion policy.
Resupplying an extra selects its existing ownership during partial builds, so
repeating or editing it does not collide with itself. Moving an extra page under
the same stable key retires its old output. Omitted extras remain retained during
partial builds; artifacts use their output path as identity, so retiring an old
artifact path requires a full build without that declaration. Different retained
owners still block colliding destinations.

A partial sitemap rebuild includes retained extra pages using their saved
category and `sitemap` flag. This works after fingerprint-cache loss and applies
equally to native and XSLT sitemap writers. If a retained page's route metadata
is unavailable, sitemap planning requires a full build with the site's current
page declarations, even when no route catalog was requested. Resupplied page
declarations replace the retained key's inclusion policy; a full build omitting
that declaration removes the old page.

Ownership decoding admits exact integer versions 1 and 2. Version-2 publication
identities are absent (`None`) or two nonnegative, non-boolean integers.
Malformed versions or identities reject before ownership can authorize output
replacement or pruning. Do not use a disposable cache to repair invalid
authoritative ownership data.

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

`composition_contracts.ExtraArtifact(output_path, bytes)` declares a non-page generated
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

`builds.capture_site(cli, config, root)` offers the same lifetime-scoped source
capture for authoring/audit tools without rendering or publishing. It validates
the site configuration, captures source records/policies once and creates no
output/cache files or publication locks. Consumers may retain immutable article
records, but must finish/close borrowed iterators within its context. Morpha's
source requirements are applied by one `portal/source_policy.py` adapter shared
by ordinary builds and source-audit tools.

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
global merge explicitly registers and closes each child iterator; retaining
another reference cannot postpone that settlement. Cleanup exceptions still
run the remaining child/spool cleanup callbacks before propagation (LIFE-001).
This is explicit resource settlement, independent of garbage collection. A
retained article record remains valid because its bytes are owned. Template and
policy callbacks are synchronous trusted code, not sandboxed plugins. Exceptions,
invalid results and capture failures release their owned resources and do not
publish. Source/template storage scales with admitted content and generated
inputs; callbacks fund any records they retain and must not retain live handles
past context exit. These APIs do not promise an atomic snapshot of unrelated
source-tree files being edited by another writer.

Each snapshot lazily sorts a language once and reuses that immutable batch.
Every iterator opens its own read handles; closing one reader leaves other
readers and shared sort files valid. Snapshot close settles active readers and
clears batch references before its workspace removes the files, including after
sorting failures. The three-article/two-language regression retains five files
after both one and ten complete reads, with unchanged bytes after the first
read; the previous implementation retained 23 files after ten reads. Storage now
depends on captured content and sort chunks, rather than successful read count.

[`articulous.builds`](../articulous/builds.py) exposes a context-managed whole-site
lifecycle through the independent `build_contracts.BuildAPI` interface.
`build_contracts` defines opaque prepared/staged/validated capabilities, read-only
route/artifact views, diagnostics, reports, validators and errors without importing
planners, storage, native locking or XML implementations. Implementation state has
one private owner; handles expose no cache, task plan, workspace or build context.
These APIs merge and validate a copy of the supplied configuration,
resolve paths against `project_root` and require an unfiltered build. They reject
`only_sections`, `only_langs` and `only_slugs`; incremental partial builds remain
available through `run_build`. Whole-site preparation always captures and renders
a fresh generation, regardless of `cli.dry_run` or fingerprint-cache hits.

```python
from articulous.builds import (
    check_build, prepare_build, render_prepared, validate_generated,
)
from articulous.build_contracts import Diagnostic

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
after capture apply to the next build. The prepared context owns locks, route
storage and temporary resources; staged and validated handles expire when it
exits. `PreparedBuild.state` and `closed` are read-only views of its single
lifecycle state. Calling `close()` retires handles and settles readers;
containing-context exit reclaims workspaces and locks. Keep the handle to retry
if reader settlement raises. Unknown close obligations stay attached to that owner.

Assets are copied safely into private inputs once during preparation. Rendering
renames that captured directory into staged output on the same filesystem;
the private-stage owner retains cleanup responsibility throughout the handoff.
No hardlinks or borrowed source files survive capture. Content and stylesheet
capture still use their existing snapshot boundaries.

`StagedBuild.routes` exposes a read-only `RouteReader` without storage mutation
or close methods. Each iteration checks lifetime before touching its native
reader. `open_artifact(relative)` admits a scoped `ArtifactReader` with
`read(size=-1)` and a read-only `closed` cutoff flag, without exporting descriptors.
Sizes are non-boolean integers: -1 or nonnegative. Reads are clamped to remaining
file bytes admitted on open, so huge integer sizes cannot allocate unbounded
buffers. Context exit and publication handoff settle retained artifact readers;
reads after cutoff fail before native access. Paths stay inside the stage;
absolute, dot-segment, backslash and drive-style paths are rejected.
`validate_generated` verifies manifest targets, runs each validator and
checks the fingerprint again. A validator returns an iterable of `Diagnostic`
values or `None`; severity `error` rejects the build, while `warning` is retained
in the report. Exceptions and staged mutations also prevent publication.
Every revalidation retires earlier validation handles before checking artifacts
or invoking callbacks. Rejection leaves the generation rendered and requires a
fresh successful validation. Earlier handles stay invalid after a later success;
use the newly returned handle to publish.

Validators are trusted, read-only caller code. The engine does not sandbox them
or implement HTML/link/fragment/canonical/search checks for every theme. Provide
those checks through validators before publishing. `check_build` renders,
validates and discards its stage, leaving published output, cache and ownership
bytes unchanged. Lock files may remain after release. A changed staging-directory
identity is preserved for inspection instead of recursively deleting its replacement.

## Transformation boundary

`transform_contracts.TransformEngine` defines the structural engine interface,
path/byte inputs, read-only string parameters and synchronous `None` result
without importing lxml, storage or native adapters. Independent providers can
implement it directly. `ExecutionCapabilities.external_process` controls automatic
worker selection and remains visible through stylesheet-capture wrappers.

Concrete adapters use the shared `engines.XsltEngine` implementation. Their public
preparation/render boundary reports `TransformFailure(operation, detail,
returncode=None)` rather than requiring callers to catch lxml/subprocess types;
original exceptions remain chained for adapter diagnostics. Invalid parameter
types and capture states reject explicitly. Inputs and parameter mappings are
stable caller borrows until synchronous return or failure; retained stylesheet
snapshots belong to the engine's containing build context. Existing atomic-output
scopes preserve prior output on failure.

The Linux Saxon adapter copies XML and stylesheet inputs into private directories
before starting native work. For path inputs it records the original effective
document base as `xml:base`; byte inputs retain the existing explicit-base policy.
The source copy may therefore contain this XML metadata attribute. The engine
cache identity includes the owned-input transport revision.

`backends.saxon.run_transform_command` owns native descriptor admission and
process supervision. Shared `browser_process.observe_session` consumes the
independent `ProcessSession` interface without descriptor arguments. Saxon enables
`SessionOptions.seal_on_exit`: observing the leader's exit stops remaining group
members, establishes quiescence, drains diagnostics and releases the PID lease
before atomic output installation. Native stdout/stderr remain visible after
supervised execution settles. Commands that leave the admitted session/group are
outside this containment contract.

Uncertain native settlement raises the independent
`process_contracts.NativeCleanupError`, preserving its recovery token. Private
input directories transfer to the retained reservation instead of being deleted;
the previous output remains unchanged. Failed handoff storage preserves those
directories and adds manual-recovery paths to the same exception. Recover known
reservations before releasing their copies; unacknowledged paths or missing
identity evidence require manual inspection. See
[native supervision and recovery](#optional-native-test-supervision).

## Native publication boundary

`publication_contracts.PublicationCapabilities` and `lock_contracts` contain
independent data/interfaces. Importing capability, composition, catalogue and
resource-lock contracts does not load CLI or native locking. The checkout
launcher invokes `articulous.cli.main` directly; package initialization has no
eager CLI re-export.

`publication.lock_site(cli, config, root)` takes the same normalized output and
cache locks as whole-site and incremental builders. Use it while copying a
published generation for deployment or live comparison. It does not render,
publish or silently recover a pending transaction. `ownership.validate_owned_output`
is the shared read-only ownership check used by the publisher and release
adapters; a site's report file is not ownership proof. `resource_locks.resource_lock`
provides independent state-file exclusion, using the same native file-lock
primitive through a lazy backend. Its path names the lock file, whose parent
may be created; the persistent lock inode remains after release. Body exceptions
are not misreported as contention. Callers must exclude other writers that can
replace those lock paths. POSIX lock availability and Linux validation remain
separate from the Linux-only publication capability.

[`articulous.publication`](../articulous/publication.py) provides shared
orchestration through the independent `publication_contracts.PublicationBackend`
protocol: `capabilities`, `locked`, `recover` and `publish`. The contract module
imports no build, storage or native adapter implementation. `publish` accepts a
`PublicationInput`: staged root, destination, cache path, serialized cache text,
read-only output ownership entries and a `verify()` callback. The boundary adapter
also supplies immutable route values through read-only `output_routes`; the
native publisher persists those alongside ownership without interpreting cache
serialization. The boundary adapter
serializes shared build metadata; native backends never receive engines, task
queues, route catalogs or concrete build handles. Native operations live in
[`backends/posix.py`](../articulous/backends/posix.py) and the existing
[`filesystem.py`](../articulous/filesystem.py) adapter primitives. Configuration,
route serialization, models and validation hooks remain shared.

The preparation context owns the staged tree and validation capability. The
backend borrows them only for the synchronous publication call under the retained
site locks, verifies immediately before native handoff, and must settle native
work before returning or raising. It must not retain the input or callback.
Serialized metadata is an immutable call-scoped snapshot bounded by the admitted
cache and output inventory. Success advances the authoritative build lifecycle to
published; failure preserves its existing rollback/recovery ownership. A saved
validation callback rejects use after lifecycle cutoff. These portable contracts
do not establish Windows or macOS native publication support.

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
Shared path admission reserves this tree against configuration, source, cache,
log, lock and ownership paths. It checks both lexical and resolved aliases;
native lock/recovery/publication entry points also reject overlapping cache
paths before effects. Nearby filenames with a different path component remain
valid. The reservation prevents a cache write from replacing the journal
directory or rollback from treating that directory as a cache file.
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

### Image maintenance

`articulous.image_optimization.optimize` is a separate, explicit maintenance
iterator. Supply an `image_contracts.ImageBackend`, roots, format choices and
size/quality thresholds. `backends.imagemagick.ImageMagick` adapts installed
`convert`, `identify` and optional `optipng`; no tool is downloaded. The iterator
owns one private scratch workspace until exhaustion/close. Consumers that can
stop early must close it, including on cancellation. Each conversion settles
before its result is yielded; apply mode atomically replaces a source only if
the result is smaller and its captured file identity, metadata and content still
match. Changed, deleted, replaced and symlink sources are rejected. The final
check and replacement hold the persistent sibling `.<filename>.articulous.lock`
via `resource_locks.resource_lock`; cooperating writers must acquire that same
lock and leave its inode in place. Callers must exclude uncooperative writers
and directory replacement during this handoff: content checks alone cannot
provide filesystem isolation. Conversion/replacement failure leaves owner edits
intact. The lock descriptor and replacement staging directory settle before yield;
the persistent lock file is retained for subsequent acquisitions.
The source batch and largest selected image bound storage; caller owns admission
and returned `ImageResult` records. Native PNG dimensions and EXIF-oriented JPEG
rotation/format/metadata stripping are tested on Linux; other native platforms
have no validation claim. Missing executables remain visibly unavailable.

### Local size metrics

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
Rollback checks the installed file's device/inode, permissions and content before
restoring or removing it. Conflicting edits, replacements and deletions remain
untouched; failed rollback retains its backups and names the workspace for caller-owned
recovery. Checks and replacements still require the caller to exclude concurrent
mutation during the individual filesystem operation; they provide no atomic compare-and-swap.
A cleanup failure reports the retained path without reversing a
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

## Optional local preview

`python -m articulous.preview OUTPUT --port 0 --not-found /404.html` serves
loopback only. Supply repeatable `--internal` names for site hosting artifacts.
Dotfiles, traversal, escaped symlinks and directory listings are refused; GET
and HEAD use the configured rendered 404, with a plain response when absent.
Preview sends `no-store`; it defines no production hosting cache policy.

The server owns each admitted socket by object identity, cuts admission on
close, shuts down those sockets under the same lock used for worker release,
and joins non-daemon workers before returning. Read timeouts bound idle request
protocols; there is no aggregate session runtime cap. The caller must stop any
separate serving loop before closing the server. Root files are borrowed for the
server lifetime; preview is for trusted generated trees, not hostile concurrent
filesystem mutation. Native socket settlement is tested on Linux.

## Opt-in publication validation

`validation_contracts.ValidationPlan` supplies explicit output-page canonical
URLs, searchable URLs, sitemap URLs, JSON/XML locations and site-relative
redirects. `site_validation.validate_site` checks the staged tree before
publication and returns scalar counts. It follows same-origin links inside the
configured publication prefix, decodes paths/fragments, follows redirect
fragments, ignores inert templates and remote/outside-prefix URLs, and reads
sitemap indexes without revisiting a shard. No language or theme paths are
assumed. Sitemap XML disables entity resolution and networking.
Redirect sources and intermediate hops need no generated stub files; only the
terminal local target must exist. Cycles remain validation failures.
Absolute HTTP(S), root-relative and empty deployment bases all admit their local
links for checking. For originless bases, URLs with an explicit scheme or host
remain unowned. Each redirect carries the effective URL forward: a target
fragment replaces the incoming fragment, an absent fragment inherits it, and an
explicit empty fragment clears it. Anchors are checked against the final HTML
target, including percent-decoded fragments and text-fragment handling.

Supply an optional HTML error callback for a stricter parser. Morpha supplies
its existing HTML5 parser and retains its interface/mirror audits. The standalone
portal auditor's separate scope decision (REV-092) remains unresolved.
Validation borrows a stable staged tree and caller-owned expectation mappings
for one synchronous call. Compact records own plain strings, never parser DOM
references. File parsers close their inputs before return; retained state is
bounded by the admitted publication's pages, references, routes and sitemap
entries. Diagnostics retain all findings.

## Optional taxonomy authoring

`taxonomy_policy.TagPolicy.from_mapping` validates caller-owned removed/merged
rule data, rejects overlapping rules, merge chains and cycles, and reports the
required source correction. It never rewrites a generated route. Morpha's loader
selects `data/tag-policy.json`; exact owner vocabulary remains in that repository.
`taxonomy_completeness` offers opt-in literal/translation-group completeness
checks over immutable `TagSummary` records.

`taxonomy_reports` shares normalization, candidate/group matching and full
duplicate totals with a bounded sample (default 20, configurable); it does not
select vocabulary or print editorial advice. `taxonomy_editing.apply_map` takes
a `TaxonomyLayout` and optional `ProvenanceLayout` with caller-defined source
reference and fingerprint projection. The XML adapter stages all edits in one
source transaction. Only provenance already current before the edit can advance;
stale/missing hashes stay stale. Morpha supplies its language/file schema and
16-character digest projection. XML entity resolution and network access are
disabled.

The synchronous edit owns parsed documents and its transaction workspace until
publication/rollback settles; no DOM or workspace escapes. Inputs and callbacks
are borrowed for that call. Storage scales with the admitted XML corpus; output
report sampling does not cap findings. Source-edit and partial-failure tests
retain the existing identity-bound transaction cleanup guarantees.

## Protected-markup authoring

`markup_contracts.MarkupPolicy` defines opaque/inline/block/void tags and
translatable attributes independently of the lxml codec. `markup.encode_block`,
`decode_block`, `block_units` and `loose_text_nodes` share protected markup
handling. Signature comparison accepts an explicit link-rewrite callback; no
language or route scheme is embedded. Morpha adds its `site-value` and
`projects-list` widgets and provides its own language-link projection.

An `Encoded` object owns placeholder text/snapshot bytes and borrows the original
tree through its root/slots. Decode requires that exact, unchanged root and
consumes the borrow on success, rejection or exception. `close()` explicitly
settles an unused borrow. Candidate reconstruction happens on a detached tree;
rejection preserves original node identities as well as bytes. On success the
root remains, while its children are replaced by the validated candidate. No
slot may be reused after consumption. Callers retain selected block/loose-node
views only while their containing document remains owned and unchanged.
Storage is bounded by the admitted document and translated unit. These structural
checks establish no semantic translation accuracy.

## Optional translation jobs

`translation_contracts` defines provider/cache/job contracts and XML layout
configuration without HTTP, SQLite or portal types. `translation_client.Translator`
borrows a provider, cache and prompt/normalization/log callbacks for sequential
requests. One effective prompt snapshot participates in both cache identity and
the provider request. Identity includes provider/model/generation settings,
languages, input and markup mode; timeout/retry budgets do not change meaning.
Invalid cache values are evicted and invalid provider output remains retryable.
`backends.translation_http.HttpProvider` is explicitly invoked; it starts no
model server and closes HTTP responses on success, schema failure, interrupted
reads and rejected HTTP status. Status failures preserve the original
`urllib.error.HTTPError` diagnostics with the response closed. If response close
itself fails, the exception chain retains the response-owning error for explicit
cleanup retry. `TranslationProvider.model` is a read-only contract property;
providers may expose immutable model identity.

`tests/test_translation_http.py` uses a controlled loopback provider to verify
real request encoding, Unicode responses, malformed bodies, status failures,
disconnects, deadlines, retries, cancellation and socket settlement. Failed units
retain source text and add no successful cache entry; incomplete drafts carry no
clean provenance.
The [HTTP acceptance record](../reviews/http/README.md) states the regression,
fault-control and lifetime scope; no remote provider is needed.

`translation_cache.open_cache` owns the SQLite connection through all exits.
`translation_jobs` shares bounded file-budget selection, provenance-chain
confinement, handwritten/current-target filtering and queued target-change
fences. The caller chooses corpus, languages, source preference, paths, current
checks and execution callback; dry-run stays outside cache/provider acquisition.
`translation_xml.mirror_xml` translates caller-configured XML fields and markup,
checks captured source/target state again before atomic replacement, and stamps
a clean digest only when no unit failed. Morpha owns its prompts, language names,
article/page layouts, provenance reader, link rewrite and all-language policy.

Jobs own temporary parsed trees and snapshots for one synchronous execution;
encoded borrows are closed even on provider exceptions. File replacement owns
its private workspace until publication or rollback settles. Provider responses
and caches have separate owners; completing a job does not close a borrowed
client/cache. Retry counts, HTTP deadlines and admitted corpus/response sizes
remain caller contracts. No model download, startup or remote request is implicit
in discovery, preview or import. Structural success is not semantic acceptance;
Morpha REV-139/HOST-017 remain separate owner work.

## Optional content and code resources

`theme_resources.code_resources()` returns immutable path/byte records from
installed package data. The caller exports them into its private source stage;
Morpha rejects any source file shadowing these shared paths. The bundle contains
the sanitizer/code XSL, pinned Prism dependency bytes, maintained copy plugin and
code adapter. Wheel import was verified locally without installing/downloading
packages. Provenance, upstream hashes and the maintained patch live under
`theme_assets/third_party/prism`; declarations live under `theme_assets/contracts`.
The unchanged-upstream coverage exemption remains exact-hash only.

Include `xsl/components/articulous/content.xsl`; call `render-code-block` with
copy/success/error labels and `render-paragraph` with the desired wrapper class.
Sanitization and exact code/leading-line handling are shared. Site-specific image,
table, embed, widget and localization policies remain in the site's stylesheet.
The JS adapter has no automatic DOM admission: call
`CodeBlocks.init(document, selector)` or mount individual code containers, then
dispose controllers before reusing those identities. The existing plugin fences
late clipboard results, timers and listeners by controller identity. Prism remains
optional theme tooling; generator core adds no default JS dependency.

Repository acceptance runs `tests/test_code_browser.py` with
`tests/tooling/code-browser.mjs` and `code-block-page.js`. Sixteen native Chromium
scenarios cover invalid/detached admission, exact text and markup, language
normalization, labels, success/rejection, disposal, remounts and stale callbacks.
V8 counters independently checked against parsed source inventory require >=80%
executable lines for every maintained function. The recorded Linux Chromium
149.0.7827.55 run measured all 25 functions and both module bodies at 100%; see
`reviews/browser/README.md` for source hashes, reproduction and limits. Clipboard
promises are controlled by the fixture; this is no claim of OS clipboard or
browser permission acceptance. No upstream hash exemption is expanded.

Resource reads close each package input before return; records own immutable
bytes bounded by the fixed package inventory. Exported stage files live under
the caller's private-stage owner and are released with it.

## Optional native test supervision

`browser_process.run_browser` preserves explicit protocol deadlines;
`run_browser_suite` observes settled-stage checkpoints without a total runtime
kill cap. `run_owned` adds native exit-status checking for local tools, including
the ImageMagick adapter. `python -m articulous.browser_process COMMAND ...` runs
a checkpointed command. The Linux backend owns each Popen child, captured pipes,
selector, private scratch and materialized JS helpers. It borrows stdin.

`process_contracts.SessionOptions` independently defines helper admission and
checkpoint snapshot policy, plus optional group sealing on leader exit.
Saxon selects sealing explicitly; browser entry points retain their existing
caller-owned lifecycle and admit the fixed helper
inventory by default. ImageMagick commands pass `tooling=False` through
`run_owned`, avoiding helper reads/writes and removing inherited helper URLs.
Admitted helpers still use session-owned captured bytes and the same cleanup
fence; converter targets retain their existing borrowed-workspace ownership.

Checkpointed suites copy only new complete stderr lines into timeout records;
they do not snapshot stdout at checkpoints. Two session-owned cursors scan each
new stderr byte once and commit only after snapshot allocation succeeds.
Temporary buffer views are released on success and failure. Partial lines stay
in the authoritative buffer until complete, and completion returns full stdout
and stderr. Fixed-deadline sessions retain accumulated timeout diagnostics.
The containing session owns diagnostic buffers until released; callers fund
their admitted finite command output. Checkpointing imposes no new output or
runtime cap, and cancellation follows the same native fence and recovery path.

The child PID remains reserved through `waitid(WNOWAIT)` observations, group
quiescence, byte drainage and selector/pipe closure. Reaping releases that lease
last. UTF-8 decoding happens separately: malformed diagnostics cannot prevent
native cleanup. Signal/reuse operations never rely on a cached numeric PID after
reaping. Uncertain fences retain the lease and scratch in a recovery broker.
`NativeCleanupError.token` is an opaque identity; `recover_session(token)` claims
that exact reservation, restores it on incomplete recovery and removes it only
after settlement. Cleanup interruption restores that exact token and its remaining
workspace obligations for retry; identity checks prevent deleting replacements.
Tokens with equal PID/path fields do not alias. ImageMagick
transfers its borrowed image workspace and allocation identity to the same
reservation when native settlement is uncertain. Recovery releases that directory
only after the process fence. A failed transfer preserves and names the directory
for manual recovery; it never deletes a potentially live conversion target.

The isolated Node session receives helper URLs through environment variables.
`connectCDP` owns request timers/listeners and exposes `dispose`; the caller owns
the socket. `createProfile` records directory identity. `stopBrowser` closes
HTTP admission and deletes that profile only after native evidence and server
closure. Linux libc pidfds bind signals to process generations; the force fence
freezes the admission-closed cohort, collects forked members, kills through
pidfds and waits for their native exit notifications. The containing Node group
leader remains alive during this fence. Commands must remain inside their
owned session/group and callers must stop new admission before teardown.
Workloads that leave the admitted session/group are outside this containment contract.
Linux/libc behavior is validated locally; Windows/macOS supervision is unsupported.

Native tests cover real Chromium, stubborn descendants, unrelated-process
isolation, converter cancellation, partial initialization, retained recovery,
malformed output and interruption around reaping. A five-state exhaustive model
checks one group/workspace with two captured pipes; a native trace is checked
against its independent ownership ordering. This finite model assumes trusted
containment and eventual fence/recovery evidence; it does not prove unrestricted
OS/kernel behavior. Leak freedom is conditional on eventual native exit, successful
resource close and a caller/operator that performs retained recovery.

A retained native session also owns a private `WORKSPACE.recovery.json` file
beside its scratch directory. The versioned record contains the Linux boot ID,
owner and native PID/start-time generations, and every acknowledged scratch or
borrowed directory allocation identity. Replacement is atomic; file and parent
directory are synced before successful handoff. Records are bounded to 1 MiB.
The journal stays outside the directories it protects and is removed last, after
all cleanup succeeds. Interrupted cleanup can retry already absent directories;
replacement identities, storage failures and unavailable native evidence retain
the reservation. Recovery serializes claims on the journal's exact file identity.
New sessions skip scratch names with existing journals, including after partial
cleanup. Journal updates must match the existing boot/process reservation and
cover its workspace obligations before replacing it.

After Python-owner loss, an operator can run:

```sh
python -m articulous.backends.processes /tmp/articulous-owned-EXAMPLE.recovery.json
```

This command refuses a live owner, a live native generation, a live contained
group or changed identities. It never signals a numeric PID. The operator must
first establish any required native stop fence with identity-bound tooling;
recovery observes quiescence before releasing directories. A changed boot ID
establishes that the earlier kernel's processes cannot still access them.

The owner-loss model exhausts eight states for one owner, one native group, one
scratch directory, one borrowed directory and one durable journal. It checks
retention while either actor is live and reachability of full cleanup after
owner loss and a native fence. Conditional eventual cleanup assumes operator
retry, eventual native exit, successful storage/close operations, readable and
complete same-namespace `/proc` evidence, unchanged allocation identities and
the existing admission-closed group containment contract. It does not cover
detached workloads, kernel failures or automated termination by an external
supervisor. Owner loss before a durable reservation is established, or during a
failed workspace handoff, still requires manual recovery. No unknown workspace
may be reused or deleted without exact identity and quiescence evidence.

Native V8 counters gate every measured tooling function at >=80%, alongside the
repository code/clipboard browser gate and the search client's Node gate.
Sources are retained by native script identity
before context destruction; missing or changed sources/counters fail. Unit faulty
controls remain separate from production native measurements.

The coverage gate independently parses each source with installed Acorn 8.17.0
(ES2022 modules) and requires counters for every explicit function, method and
module body. Missing lazy/nested functions cannot disappear from acceptance.
Ranges must have finite integer counts, valid source boundaries and nested
containment; duplicate or unknown function boundaries fail. Module counters
cannot substitute for a function spanning the same source range. Native mapping
for implicit class-field initializers and static blocks is unsupported and fails
explicitly; no maintained measured module uses those scopes. ASTs and inventory
records are scoped to a report call and bounded by its admitted source/counters.
Only scalar coverage rows escape; the caller retains ownership of source data.
Configure `ARTICULOUS_ACORN` for an existing parser outside Node's lookup path;
the tooling performs no dependency download.

## Optional search client

`theme_resources.search_resources()` supplies `assets/js/search-client.js`.
Its `SearchClient` factory takes an explicit origin, loader, metadata preparation,
selection/matching policy and renderer callbacks. The library validates index
records/URLs, owns immutable prepared data and one retryable request/cache, and
renders every match in bounded batches (default 200, configurable). It assumes
no language segment, tag destination, search URL, card DOM or localized labels.
Slug normalization shares the engine contract. Declarations are packaged under
`theme_assets/contracts/search-client.d.ts`.

A nonempty search admits the first load synchronously, preserving Morpha's
existing request/reset contract. Reset advances a revision and retains reusable
validated data. Dispose advances the cutoff, aborts the loader/task signal, closes
owned MessageChannel ports and clears callback/data references. Stale loads and
render batches cannot publish or invoke released render callbacks. Custom loaders
and schedulers must honor abort/eventual settlement; their external resources
remain caller-owned. Storage is bounded by the admitted index, matches and
in-flight renderer containers; there is no result cap. Morpha's static document
owns its controller until browser context destruction. Reusable consumers must
call `dispose` before releasing/reusing their render owner.

Morpha keeps language inference under its guarded article-route contract,
exact-tag-first/fallback matching, three-chip card presentation, selectors and
wording. Repository tests in `tests/test_search_resources.py` run neutral Node
consumers for complete results, malformed/retryable input, batching, callback
failures and reset/disposal interleavings, with native >=80% function counters
for the shared client. Native Chromium acceptance for Morpha's search UI is
outside this repository's suite; its browser gate covers the code adapter and
clipboard plugin.
