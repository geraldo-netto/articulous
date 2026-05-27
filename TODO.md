# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to the `articulous/` package.

---

## security

_(all open items resolved; tracked via git history)_

## performance

_(all open items resolved; tracked via git history)_

## scalability

_(all open items resolved; tracked via git history)_

## concurrency

_(all open items resolved; tracked via git history)_

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

_(all open items resolved; tracked via git history)_

## decoupling

_(all open items resolved; tracked via git history)_

## business/design patterns/DDD

_(all open items resolved; tracked via git history)_

## reliability/correctness

_(all open items resolved; tracked via git history)_

## observability

_(all open items resolved; tracked via git history)_

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| WIRE-07 | open | S | `site.site_name` is declared in `DEFAULT_CONFIG` (`articulous/config.py:30`) and set in the fixture site (`tests/fixtures/site/config.json:18`) but no production code reads it. Models / synthesised XML / RSS channel header have no `<title>` / `<channel>` element fed by this value, so a custom `site_name` in config makes zero observable difference in output. | Decision: surface in cross-lang XML — at minimum the RSS `<rss>` root and sitemap/index roots should carry a `site_name` attribute (or a `<channel><title>` child for RSS) sourced from `ctx.site_name`. Requires plumbing `site_name` through `BuildCtx`, then extending `_rss_doc` / `_index_doc` / `_tag_doc` and their fixture XSL templates. Alternative: drop the key from `DEFAULT_CONFIG` to stop pretending it does anything. |

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEAD-01 | open | S | `load_articles` (`articulous/articles.py:213`) — public-shaped callable, no production caller. Pipeline switched to `iter_articles` for bounded memory; only `tests/test_articles.py` (5 tests) exercises it. README has no reference. | Decision: delete. The streaming path (`iter_articles` + `_stream_projections`) covers every production code path and the "sorted in-memory" mode no longer earns its surface area. Drop fn, its tests, and the `:func:`load_articles`` mention in `iter_articles` docstring (`articles.py:193`) + `pipeline.py:189`. |

## documentation

_(all open items resolved; tracked via git history)_

---

## Open — parked

_(none yet)_

## Audit picks deliberately rejected

_(none yet)_
