# Generator composition assessment

ARCH-001 recommends extending Articulous's existing route and model planning,
then exposing composition and publication interfaces. Morpha should retain its
content, templates, contact and project data, localization choices, and hosting
policy. Copying the portal wrapper wholesale into the engine would couple these
concerns and duplicate existing safety checks.

This is an assessment and proposed contract, not a shipped API. The current
behavior below was checked against Articulous `d7624a8` and the Morpha source at
`d040d69d658ab7d8b6f7c1af586972304a3a87f2`. Morpha's working tree contains local
changes, including README and TODO changes; references describe the inspected
working tree. No Morpha files or existing runtime contracts were changed.

## Current ownership and recommendations

| Capability | Current implementation and evidence | Recommendation |
| --- | --- | --- |
| Language roots and page one | [`build_index_models`](../articulous/models.py) emits numbered pages and emits nothing for an empty language. `section_pattern` removes the default language prefix but keeps `/page/1/`. Morpha's [`archive_models`](../../morpha-portal/portal/build.py) separately renders roots, including empty languages; [`index_aliases`](../../morpha-portal/portal/routes.py) and its index template retain numbered page-one redirects. | **Move** optional canonical first-page routing and empty landing models into Articulous. Preserve the current numbered, nonempty defaults. Morpha opts in only when its COMPAT-003 contract decision is resolved. |
| Pagination and route discovery | Articulous owns index and tag models, navigation, stable article ordering and pagination. Morpha's [`articulous_routes`](../../morpha-portal/portal/catalog.py) recalculates index page counts and calls `build_tags_models`; its root builder also recalculates totals. | **Move** route discovery into the engine's actual build plan. All consumers should read the same planned routes, independent of sitemap policy. Retain existing streaming article stores and model builders. |
| Static pages | Morpha's `portal_models` reads portal XML, chooses translated/bare routes and creates template inputs. Articulous's [`SECTION_SPECS`](../articulous/sections.py) has no static-page section. | **Split**: accept explicit extra page models in the engine; retain Morpha's source discovery, XML schema, editorial content and translation choices. A generic CLI page loader is a separate future need, not a prerequisite. |
| Tag indexes | `build_tags_models` already generates tag archives. Morpha's `tag_counts`, `append_tag_counts` and `tag_index_models` supply vocabulary indexes and counts. | **Split**: share tag membership/count projection and optional tag-index models; retain sidebar limits, labels, sorting for display and templates in Morpha. Do not silently merge distinct labels that collide after slug normalization. |
| Not found page | Morpha supplies the model, template, `/404.html`, `noindex`, and Apache `ErrorDocument`. | **Split**: an extra page can carry an explicit not-found role and sitemap exclusion. Keep its path, language, appearance and server directives portal-owned. Rendering a file does not establish HTTP 404 behavior. |
| Sitemap | Articulous's `_append_sitemap_listings` uses index/tag models when `include_listings` is true. Morpha's `plan` adds static pages and optional roots/tag indexes; its [`sitemap.xsl`](../../morpha-portal/xsl/pages/sitemap.xsl) combines these and removes aliases. | **Move** composed route inclusion into one engine projection, consumed by native and XSLT backends. Keep article publication/indexing policy and existing shard limits. Static pages remain independent of the listing toggle; aliases and not-found pages stay excluded. |
| Generated output validation | Morpha's [`validate_output`](../../morpha-portal/portal/validate.py) checks HTML, links/fragments, canonicals, search membership and sitemap targets before publication. Articulous validates plans, paths and native formats but exposes no equivalent whole-site validation boundary. | **Split**: engine supplies staged artifacts, route manifest and validator hooks; Morpha retains its concrete HTML/theme and publication expectations. Generic validators may later move behind an optional dependency. Do not add HTML parsing dependencies to the core merely to expose hooks. |
| Whole-site publication | [`run_build`](../articulous/pipeline.py) locks, plans, journals ownership, mirrors assets and publishes individual files. Morpha stages an entire source/build, validates it, then renames the old output aside and the new output into place. | **Split**: reuse engine locks, ownership and atomic file writers through a native adapter; add a shared staged-build lifecycle. Keep deployment destination, host rules and remote upload policy outside it. |

`OutputManifest.record` already rejects duplicate keys, duplicate destinations,
and file/parent conflicts. `_record_planned_output` enforces the asset namespace
and safe paths. These checks should cover composed pages during planning, instead
of Morpha discovering engine/portal collisions in `render_extra` after rendering.

Articulous's `atomic_output(..., generated=True)` protects one destination using
directory/file descriptors. It cannot atomically replace an entire populated
directory. Morpha's two directory renames leave an interval without `output/`;
its exception handler attempts rollback, while a killed process requires the
manual recovery documented in its README. Neither implementation establishes
continuous whole-site visibility or crash-durable publication. Those are distinct
capabilities that any new publisher must report explicitly.

## Proposed public contracts

All names in this section are proposals. Existing `run_build`, configuration
defaults, templates and model calls keep their current behavior until a separate
implementation lands with regression coverage.

### Index options

Extend `build_index_models(articles, lang, ctx, *, options=IndexOptions())` with
two immutable options: `first_pattern: str | None = None` and
`include_empty: bool = False`. Mirror these as optional `urls.index_first`
and `site.pagination.empty_index` settings. The current `urls.index` remains
the pattern for later pages, and for every page when `index_first` is null.

The proposed first pattern requires `{lang}` and forbids `{page}` and unknown
fields. It uses existing local-directory URL validation, encoding and output
collision checks. Default-language prefix removal applies to it when `index`
is in `site.bare_default_language`. Thus `/{lang}/` produces `/` and `/fr/`
for Morpha, while later pages retain `/page/2/` and `/fr/page/2/`.

`include_empty=True` produces one page with `page=total_pages=1`, no articles
and empty navigation URLs. Page two links back to the canonical first pattern;
no numbered alias or redirect is generated. Validate option types, language
membership and positive non-boolean page sizes at the public boundary. Existing
callers still provide publication-filtered, stably sorted article collections.
Preserve one-page-at-a-time consumption instead of materializing all articles.

### Composed routes and extra pages

Expose an immutable `Route` with a stable key, section, optional language,
canonical URL, relative POSIX output path and sitemap category. Categories are
`article`, `static`, `listing`, and `excluded`; the article category additionally
retains its existing indexing eligibility. A not-found page is always excluded.
URLs and serialized route paths remain independent of the native filesystem.

An `ExtraPage` contains a `Route`, captured XML model bytes, and an explicit
stylesheet/engine reference. Its loader remains caller-owned. Resolve and capture
stylesheet dependencies through the existing engine snapshot path. Register
extra pages before sitemap construction, cache fingerprinting and collision
validation; reject reserved assets, escapes, duplicate keys, equivalent output
paths, and file/parent collisions across both built-in and extra outputs.

An optional `build_tag_index_model` should consume the same language-filtered tag
membership projection used for tag archives, returning label, slug, count and
first-page URL for each entry. Count each article once per tag. Preserve the
engine's collision rejection instead of adopting Morpha's independent grouping
by normalized slug. Empty enabled languages may receive an empty tag-index page.

The route catalog contains all outputs selected by the build, including cached
outputs, plus retained ownership for partial builds. It is re-iterable within the
plan lifetime and can use disk storage. Route discovery must not depend on
`include_listings`, require rendered-file scanning, or expose private task queues.
Sitemap generation selects canonical eligible routes from this same catalog,
deduplicates exact locations, and preserves URL/byte budgets and shard ordering.

### Prepare render and validate

Provide a context-managed `prepare_build(cli, config, project_root,
extra_pages=())` yielding a `PreparedBuild`. It validates inputs and captures
models/templates once, owns temporary stores and locks, and exposes route and
publication-policy projections. Exiting its context closes every resource,
including after a failed render or validation. It must not publish site output
during preparation.

`render_prepared(prepared, staging_root)` renders the exact plan into an isolated
tree. The staged result exposes its routes and a bounded artifact reader to
validators. `validate_generated(staged, validators=())` first verifies manifest
targets and then runs caller validators; any exception prevents publication.
Validators return structured diagnostics or raise a validation error. Their
contract is read-only; validators are trusted caller code, not sandboxed plugins.
The validated artifact set must be sealed or rechecked before publication so the
publisher cannot accept a different tree than the one validated.

For the initial whole-site mode, require an unfiltered build and a fresh stage;
reject `--only`, `--lang` and `--slug`. Partial/retained-output behavior remains
available through the existing incremental pipeline. Keep cache and ownership
state associated with the published generation, and never persist fingerprints
for an abandoned stage. A validate-only call destroys its stage after reporting
and leaves the published output, cache and ownership unchanged.

### Native publication boundary

Shared orchestration should depend on a `PublicationBackend` interface for
lock acquisition, creating a stage on the destination filesystem, checking
destination ownership, publishing a validated generation, and recovery. Reuse
`lock_file`, generated `atomic_output` and existing ownership checks inside the
initial POSIX adapter. Keep `fcntl`, descriptor operations, path limits, rename
semantics and process-liveness checks inside that adapter.

Capabilities must distinguish staging, exception rollback, atomic visibility,
crash recovery and durability. An unavailable capability is an explicit error;
never silently fall back from atomic visibility to two renames. Decide the
publication guarantee before selecting a rename/exchange or versioned-directory
mechanism. Unowned destinations must remain untouched. Recovery must preserve
the last known generation, report interrupted states, and retain backups when
rollback fails. Lock contention must cover both publication and shared cache
state, including callers using different cache names for the same output.

Linux is the locally exercised platform. Articulous currently imports `fcntl`
and uses POSIX filesystem facilities; native Windows remains unsupported.
macOS native validation was not performed here. A new interface alone grants no
additional platform support. Each adapter needs native acceptance for all agreed
capabilities before claiming parity.

## Delivery order and estimated cost

These are engineering estimates for implementation plus tests and documentation,
not measured performance or scheduling commitments.

| Follow-up | Work and prerequisite | Estimated effort |
| --- | --- | --- |
| ARCH-002 | Review index options; implement canonical roots and empty landings while preserving defaults. This can be designed independently of composition. | 2–3 developer days |
| ARCH-003 | Review composed routes, extra pages, tag indexes and sitemap contracts; implement after ARCH-002 settles first-page semantics. Reuse engine projections and collision checks. | 4–6 developer days |
| ARCH-004 | Review and expose prepare/render/validate lifecycle, route catalog and extension hooks after ARCH-003 fixes the composed plan shape. Keep concrete Morpha validators initially. | 3–5 developer days |
| ARCH-005 | Decide publication guarantees and design the backend boundary now; implement after ARCH-004 supplies validated stages. POSIX fault/recovery tests included; other native backends need separate estimates and platform access. | 5–8 developer days |

For Morpha's COMPAT-003, prefer the opt-in engine root capability. The alternative
is to exclude `index` from the CLI and render all index pages through the portal's
existing public `LxmlEngine.run` calls. That is viable but leaves pagination,
discovery and sitemap ownership duplicated; estimate 2–3 developer days plus
ongoing wrapper maintenance. Do not merely omit page one: pagination navigation
and empty-language roots must still be provided.

Morpha's `AGENTS.md` forbids compatibility redirects/stubs, while its current
route code and `test_index_routes.py` require them. This existing contradiction
is retained as CONTRA-002 in the engine ledger, referencing Morpha COMPAT-003.
Morpha must select its COMPAT-003 approach before replacing those assertions.
HOST-004 then removes obsolete `_redirects` generation and aliases
together, preserving `.htaccess`'s custom-404 directive. This assessment supplies
that decision's evidence; it does not resolve either portal contract by itself.
Remote hosting and the HTTP acceptance checks remain portal-owned.

## Regression requirements and evidence

Retain all existing engine and portal assertions until their owning contract
changes. For each confirmed bug fixed during follow-up work, add the permanent
test first, show it failing, then pass the same test after the fix. Keep bounded,
seeded invalid-input tests and valid boundaries. Measure each maintained
production function individually against the 80% executable-line minimum while
retaining this repository's stricter 100% line/branch suite gate and complexity
limit of 10.

| Contract | Required permanent coverage before completion |
| --- | --- |
| Canonical roots | Default and translated roots, alternate configured prefixes, encoded/base-path URLs, and absence of every numbered page-one file/redirect in the opted-in mode. Preserve current `/page/1/` defaults. |
| Empty languages and pagination | Empty enabled languages; zero, one, exact-page and page-plus-one article counts; stable equal-date ordering; forward/backward traversal with each article exactly once; invalid sizes, booleans and large valid limits. |
| Composition and collisions | Built-in/extra/cache-retained output collisions, file/parent overlap, reserved assets, normalized tag collisions, malformed routes and out-of-bounds paths; fail before output or cache publication. |
| Sitemap | Toggle listings without changing generated routes; include eligible articles/static pages exactly once; roots/tag indexes follow listing policy; exclude aliases, noindex articles and 404; native/XSLT parity, shard limits and cleanup. |
| Validation | Invalid HTML, missing local targets/fragments, wrong canonicals and search membership; validator exceptions and stage mutation prevent publication. Keep prior output, cache and ownership bytes. |
| Publication | Render/validation/rename/cache-write failures, process interruption at each publication boundary, contention/release, rollback failure and retry, unowned/symlink targets, unavailable capabilities, and native backend acceptance. Distinguish file atomicity from whole-site visibility. |

Existing Articulous evidence includes `test_models.py`'s empty-index and streaming
tests, `test_bare_default_language.py`, `test_seo_pagination.py`,
`test_tag_pagination.py`, `test_pipeline.py`'s duplicate/retained-output tests,
`test_sitemap_routes.py`, `test_seo_sitemap_shards.py`, `test_staged_output.py`,
`test_cache_recovery.py` and `test_lock_release.py`. The full Linux suite passed
1,395 tests with 16 optional real-SaxonC checks skipped; measured line and branch
coverage was 100%, and all 360 measured production functions had 100% executable
line coverage. These results verify current behavior, not the proposed APIs.

Morpha's `test_index_routes.py` currently requires aliases and empty-language
roots. `test_sitemap_listings.py`, `test_tag_index.py`, `test_not_found.py`,
`test_validation.py` and `test_engine_contract.py` provide coverage to preserve
during migration. Those six Morpha modules passed all 24 tests against the local
Articulous checkout. Reproduce from Morpha with
`PYTHONPATH=.:tests .venv/bin/python -m unittest -q test_index_routes test_sitemap_listings test_validation test_tag_index test_not_found test_engine_contract`.
The engine suite command was `.venv/bin/pytest --cov-report=json:/tmp/articulous-coverage.json`;
Pyright, Ruff and the documented C901 check also passed. Publication interruption
and native Windows/macOS behavior were not validated by this assessment.
