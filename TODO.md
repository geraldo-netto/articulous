# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| PERF-01 | wont_fix | low | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | low | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| DUP-01 | wont_fix | low | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| UNUSED-02 | wont_fix | low | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | low | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | low | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |


## Article discovery and models

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| SCAL-01 | wont_fix | low | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | low | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| REL-02 | wont_fix | low | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |


## Cache persistence

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Sitemap generation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Configuration

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| UNUSED-01 | wont_fix | low | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `config.normalize_configuration`, with direct unit tests; keep. |


## Taxonomy authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-001 | wont_fix | medium | S | Optional taxonomy matcher can retry quadratically on separator-leading names. | Security/performance review; taxonomy_completeness.py:31-44: tag `-a` produces an unanchored separator run followed by `a`; searching whitespace ending in `!` retries the run from each position. Local missing_tags cases at 1k/2k/4k characters took about 5/21/79 ms; no default build caller, only the opt-in public helper. Owner instruction 2026-10-24: stop content-focused analysis and let these findings go; no post code was executed. Declined for this pass; reconsider only on explicit owner resumption. Any future fix requires permanent failing-before/passing-after scaling/semantic controls, including literal punctuation and valid phrase boundaries. Evidence/scope: reviews/regex/README.md. |


## Browser code highlighting

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-002 | wont_fix | medium | M | Optional synchronous Prism highlighting has content-sensitive quadratic paths. | Security/performance review; code-blocks.js:29 calls highlightElement without a worker or admission bound. Packaged markup tag, Bash function and batch set-variable patterns show roughly 4x cost per doubled input in completed 1k–8k local text-only cases; no snippet was executed. Owner instruction 2026-10-24 declines further post-content/highlighting analysis and hardening. Keep disposition unless owner explicitly resumes. Future work must retain normal highlighting/copy behavior and permanent malformed-input/valid-boundary regressions, with owned cancellation if isolation is selected. Limited evidence and intentionally stopped vendor review: reviews/regex/README.md. |


## Browser search

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
