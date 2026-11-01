# SOCIAL-018 — optional image metadata

Owner requirement, 2026-11-01: optional custom-share XML uses default artwork when
absent or empty. Articulous already supplies native `<image>` and the public
`articulous-image` rendering parameter. Reuse that contract; the portal theme
owns its configured artwork. No site-specific default belongs in the engine.

`articles._validated_image` now accepts the empty value produced by the existing
Unicode-trimming field parser. Nonempty malformed URLs, duplicate/nested fields
and unrelated metadata rejection retain their contracts. Source XML is unchanged;
blank images are absent from JSON-LD. The obsolete empty-image rejection case was
removed under the owner's explicit new contract and replaced with positive blank
regressions; other rejection cases remain.

Evidence:

- `red.log`: all six new pytest cases failed before the production correction.
- `green.log`: 38 targeted cases passed, including existing SEO and input fuzzing.
- `full-tests-system-builder.log`: **3,228 passed, 16 skipped, 359 subtests passed**;
  **100% executable-line and branch coverage**, 7,743 statements and 2,396 branches.
- `per-function-coverage.log`: **989 of 989 maintained Python functions** have
  native counters and at least 80% executable-line coverage.
- The first full run (`full-tests.log`) had three packaging setup errors because
  the test virtualenv lacked setuptools. Repeating the full suite with the
  documented `ARTICULOUS_BUILD_PYTHON=/usr/bin/python3` reused installed setuptools
  68.1.2, wheel 0.42.0 and pip 24.0; all three packaging checks then passed.
  No dependency was installed or downloaded.
- `ruff.log` and `complexity-ruff.log`: full Ruff 0.15.22 checks passed, including
  McCabe <=9. `complexity-lizard.log`, Lizard 1.23.0: `_validated_image` complexity 2;
  new regression functions 1, 3 and 1. Lizard counts Python control-flow decisions
  and Boolean operations from baseline 1; Ruff supplements Python syntax checking.
- `pyright-changed.log`: changed production/test files have **0 errors** with
  Pyright 1.1.411. `pyright-final.log`: the full check still has **13 errors in
  unchanged files**, recorded as TYPE-001. This is an outstanding global gate,
  not a clean full type-check claim. The first new test import also exposed lxml
  attribution ambiguity; using its explicit `lxml.etree` module import resolved
  that new-file error. `green-final-import.log` rechecks all six new cases.
- `pyright-baseline.log`: an independently extracted, unchanged HEAD checkout,
  checked from its own root with its configuration and the same interpreter/tool,
  reproduces the same **13 errors**. The preliminary check from the portal's
  working directory did not apply that project configuration and reported 438
  errors; it is retained as `pyright-baseline-unqualified.log` and is not baseline
  evidence. Both private baseline copies were cleaned after native settlement.

The new seeded test exercises 64 whitespace values of length 0–32 and 32 malformed
fragment-bearing URLs, with seed 18018. Four explicit blank cases include NBSP.
These finite cases supplement retained native URL boundary/rejection coverage;
they do not claim unrestricted input correctness.

This change is stateless validation of a borrowed string, returning an immutable
string within the existing captured-article lifetime. It adds no allocations with
external ownership, callbacks, retained handles or reuse transitions. Pytest owns
fixture source/output paths through test settlement; source bytes are checked
unchanged after parsing. Existing build publication/cleanup ownership is retained.

Portal fallback and four-language rendered metadata evidence is in the sibling
morpha-portal repository's `reviews/social018-2026-11-01/`. No publication or
native social-client acceptance was performed.

The portal's final `tools/verify.sh` also passes: 959/959 test methods, 455/455
maintained Python functions meeting the native coverage threshold, complete
Articulous publication/audits and 1,796 browser layout observations with no
overflow. SOCIAL-018 is resolved in both ledgers; its permanent tests remain.
The independent full Pyright follow-up is decomposed into TYPE-002 import
attribution, TYPE-003 nullable accesses and TYPE-004 deliberate invalid inputs,
with TYPE-001 retaining their integration gate. No unrelated type fix was made.

Raw test/analyzer `.log` files preserve exact tool output, including diagnostic
trailing spaces. The staged whitespace check excludes only these captured logs;
maintained source, tests, documentation and structured evidence pass unchanged.
