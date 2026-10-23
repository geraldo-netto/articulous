# Agents Behavior Guide

File define expected behavior + usage model for AI agents in this repo.
Primary source for agent conduct, edit norms, response expectations — follow behavior here when interacting with workspace.

## Purpose

- Standard guidelines for agent interactions.
- Consistent behavior when using AI tooling in workspace.

## General Agent Behavior

- Prefer short, actionable responses. Terse fine; fragments OK.
- Respect workspace context. No guess when info missing.
- On code changes, clearly describe what changed + why.
- On file edits, include exact context around replacements to avoid ambiguity.

## Rules

- No assume. No hide confusion. Surface tradeoffs + ask user when unclear.
- Write minimum code that solves problem. No speculative or unneeded changes.
- Touch only what must. Clean own mess. Leave workspace cleaner than found.
- Define success criteria before changes. Verify against criteria + iterate until satisfied.
- Input-handling changes must include reproducible fuzz tests for invalid and
  out-of-bounds inputs, with valid boundary cases to prevent over-rejection.
- Every new or changed function/method must have cyclomatic complexity <=9,
  including tests, tools and drafts, without exemptions or suppressions. Split
  cohesive responsibilities when necessary. Owner clarification (2026-10-24):
  SonarQube or an equivalent installed local analyzer is acceptable. Record
  per-function measurements, analyzer/version, counting conventions and syntax
  support; validate analyzer gaps rather than treating missing results as passes.
  Track unavailable measurement in TODO.md. Do not
  download an analyzer on the metered connection without owner authorization.
- Avoid code duplication. Apply SOLID only when improve clarity or structure.
- Default no comments. Add one only when WHY non-obvious (hidden constraint, subtle
  invariant, workaround for specific bug). Record assumptions/design intent in commit notes
  not inline.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Propose business/design patterns + DDD only when improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never chat-only. Any time scan, review, audit, or "look for issues" (not just major changes), add each finding to the appropriate lifecycle table before/while reporting. Name its review category in the description or notes.
- ALWAYS report every contradiction encountered, of any kind, and add or update a
  `contradictions` finding in `TODO.md`. This includes conflicting
  instructions, requirements, code, tests, documentation, and observed behavior.
  An existing project TODO format always wins over a shared skill's default;
  this intentional precedence is not a contradiction and must not be logged as one.
  Record both conflicting claims, source references or evidence, impact, and the
  condition needed to resolve the contradiction. Never silently choose a side or
  omit the finding. Follow instruction precedence and continue unaffected work.
  Use `open` for actionable contradictions; reserve `blocked` for a named missing
  decision, evidence or prerequisite. Move it to `open` when that obstacle is
  removed; delete it after reconciliation and verification.
- ALWAYS remove completed items from `TODO.md` — once finding resolved + verified,
  delete row from table outright. No "shipped" sub-sections, no struck-through entries.
  `git log` = durable record. Keep deferred and declined items in **Other items**
  with explicit reasons so future passes do not reopen them automatically.
- Use two TODO tables: **Open items** for `open`/`in_progress`, and **Other items**
  for `blocked`, `deferred`, `wont_fix` and other dispositions. Preserve IDs and
  columns: `id | status | effort | description | notes`. Order Open by dependencies
  and priority; make prerequisites explicit. Order Other with unresolved blockers
  first, deferred work next and declined work last. Each unresolved row names the
  exact next decision, evidence, prerequisite or review needed. Review that can
  start now belongs in Open; review alone is not a blocker.
- On major changes, rescan whole project + create or update `TODO.md`, covering
  these review categories within the two lifecycle tables:
  - contradictions
  - security
  - performance
  - scalability
  - concurrency
  - code complexity
  - data governance
  - system design
  - code duplication
  - architecture/modularity/SOLID
  - decoupling
  - business/design patterns/DDD
  - reliability/correctness
  - observability when application has it
  - wiring gaps — modules/helpers/cfg knobs that exist + pass tests but have no real production call site (orphan exports, cfg flags never read, advertised backends not wired in). Shipped feature only "shipped" when dispatcher actually invokes it.
  - unused functions/methods — public-shaped callables (no leading `_`) imported by no production code, no tests, no plugins. Different from wiring gaps: these not half-wired, fully dead. Includes `__init__.py` re-exports no caller pulls + class methods only ever called from one private site. Each finding: keep / inline / delete decision recorded in `notes`.

## File Editing

- No overwrite existing files unless user explicitly asks or file missing.
- For text edits, preserve surrounding context + keep mods minimal.
- Use repo-specific structure + conventions when adding or updating files.

## Communications

- Keep responses concise and readable. Headings and bullets are optional; follow higher-priority formatting instructions.
- Highlight changed files + key points.
- Keep final answers brief + professional.
