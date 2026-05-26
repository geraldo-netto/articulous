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

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCA-01 | parked | M | All articles are held in RAM as :class:`Article` dataclasses. Fine today; a 100k-article site would bloat. Parked until a concrete need surfaces. | Streaming iterator over `content_dir`; sort lazily by chunk. `articulous/articles.py`. |

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

_(all open items resolved; tracked via git history)_

## unused functions/methods

_(all open items resolved; tracked via git history)_

## documentation

_(all open items resolved; tracked via git history)_

---

## Open — parked

- **SCA-01** — Streaming article load. No production site is large enough today for the in-memory list to bite. Reopen if profiling shows article load dominates memory or wall time.

## Audit picks deliberately rejected

_(none yet)_
