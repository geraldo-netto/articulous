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
- Keep code complexity <= 10 for any function, class, or method. Applies to all code,
  **including tests**. No exceptions. If logic needs more, split into helpers, table-drive it,
  or restructure until each function is <= 10. Flat lookup `match` (one arm = one mapping, no
  nested logic) is exempt: high arm count, no real path branching.
- Avoid code duplication. Apply SOLID only when improve clarity or structure.
- Default no comments. Add one only when WHY non-obvious (hidden constraint, subtle
  invariant, workaround for specific bug). Record assumptions/design intent in commit notes
  not inline.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Propose business/design patterns + DDD only when improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never chat-only. Any time scan, review, audit, or "look for issues" (not just major changes), add each finding to matching category table in `TODO.md` before/while reporting.
- ALWAYS report every contradiction encountered, of any kind, and add or update a
  `blocked` item in the `contradictions` table in `TODO.md`. This includes conflicting
  instructions, requirements, code, tests, documentation, and observed behavior.
  An existing project TODO format always wins over a shared skill's default;
  this intentional precedence is not a contradiction and must not be logged as one.
  Record both conflicting claims, source references or evidence, impact, and the
  condition needed to resolve the contradiction. Never silently choose a side or
  omit the finding. Follow instruction precedence and continue unaffected work;
  keep the item blocked until the contradiction is reconciled and verified, then
  remove it under the completed-item rule below.
- ALWAYS remove completed items from `TODO.md` — once finding implemented + tested + merged,
  delete row from table outright. No "shipped" sub-sections, no struck-through entries.
  `git log` = durable record. Exceptions: "Open — parked" section keeps open-but-deferred
  items with why-not-now annotation; "Audit picks deliberately rejected" section keeps
  rationale so future passes don't re-pick same items.
- On major changes, rescan whole project + create or update `TODO.md` with one table per review category.
  Each table use format: `id | status | effort | description | notes`.
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

- Use headings + bullets for readability.
- Highlight changed files + key points.
- Keep final answers brief + professional.
