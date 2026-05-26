# Agents Behavior Guide

This file defines the expected behavior and usage model for AI agents working in this repository.
It is the primary source for agent conduct, editing norms, and response expectations — follow
the behavior defined here when interacting with this workspace.

## Purpose

- Provide a standard set of guidelines for agent interactions.
- Ensure consistent behavior when using AI tooling in this workspace.

## General Agent Behavior

- Prefer short, actionable responses. Terse is fine; fragments OK.
- Respect workspace context and avoid guessing when information is missing.
- When making code changes, clearly describe what was changed and why.
- When editing files, include exact context around replacements to avoid ambiguity.

## Rules

- Don't assume. Don't hide confusion. Surface tradeoffs and ask the user when unclear.
- Write the minimum code that solves the problem. Avoid speculative or unneeded changes.
- Touch only what you must. Clean up only your own mess and leave the workspace cleaner than you found it.
- Define success criteria before making changes. Verify against those criteria and iterate until satisfied.
- Keep code complexity <= 10 for any function, class, or method. Applies to all code,
  **including tests**. No exceptions. If logic needs more, split into helpers, table-drive it,
  or restructure until each function is <= 10. Flat lookup `match` (one arm = one mapping, no
  nested logic) is exempt: high arm count, no real path branching.
- Avoid code duplication. Apply SOLID principles only when they improve clarity or structure.
- Default to no comments. Add one only when the WHY is non-obvious (hidden constraint, subtle
  invariant, workaround for a specific bug). Record assumptions/design intent in commit notes
  rather than inline.
- Prefer explicit, maintainable solutions over clever shortcuts.
- Propose business/design patterns and DDD only when they improve clarity or structure.
- ALWAYS record review findings in `TODO.md` — never report them only in chat. Any time you
  scan, review, audit, or "look for issues" (not just major changes), add each finding to the
  matching category table in `TODO.md` before/while reporting it.
- ALWAYS remove completed items from `TODO.md` — once a finding is implemented + tested + merged,
  delete its row from the table outright. No "shipped" sub-sections, no struck-through entries.
  `git log` is the durable record. Exceptions: the "Open — parked" section keeps open-but-deferred
  items with a why-not-now annotation; the "Audit picks deliberately rejected" section keeps the
  rationale so future passes don't re-pick the same items.
- When making major changes, rescan the whole project and create or update `TODO.md` with one table per review category.
  Each table should use the format: `id | status | effort | description | notes`.
  - security
  - performance
  - scalability
  - concurrency
  - code complexity
  - code duplication
  - architecture/modularity/SOLID
  - decoupling
  - business/design patterns/DDD
  - reliability/correctness
  - observability when the application has it
  - wiring gaps — modules/helpers/cfg knobs that exist + pass tests but have no real production call site (orphan exports, cfg flags never read, advertised backends not wired in). A shipped feature is only "shipped" when the dispatcher actually invokes it.
  - unused functions/methods — public-shaped callables (no leading `_`) imported by no production code, no tests, no plugins. Different from wiring gaps: these aren't half-wired, they're fully dead. Includes `__init__.py` re-exports that no caller pulls and class methods only ever called from one private site. Each finding: keep / inline / delete decision recorded in `notes`.

## File Editing

- Avoid overwriting existing files unless the user explicitly asks or the file is missing.
- For text edits, preserve surrounding context and keep modifications minimal.
- Use repository-specific structure and conventions when adding or updating files.

## Communications

- Use headings and bullets for readability.
- Highlight changed files and key points.
- Keep final answers brief and professional.
