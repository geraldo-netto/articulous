# Offline complexity acceptance

CC-003 uses installed Lizard 1.23.0 for Python and cached ESLint 10.8.1
(`complexity`, classic variant) for JavaScript. No package installation, network
access or modification of the cached analyzers is required.

From the repository root:

```sh
.venv/bin/python -m articulous.complexity_gate measure \
  --python-analyzer /usr/bin/python3 \
  --eslint /home/netto/.npm/_npx/515228b7c8d004a2/node_modules/eslint
.venv/bin/python -m articulous.complexity_gate check
```

`functions.json` records every maintained Python/JavaScript callable, source
boundary, SHA-256 identity, analyzer version and calibration results. Measurement
fails before publishing evidence if any scoped function exceeds 9. The check
command validates a trusted measurement snapshot against current sources; it does
not rerun analyzers or authenticate an edited report. Remeasure after source edits.

The inventory includes root Python entry points, all Python files under
`articulous` and `tests`, and maintained JS/MJS in those trees. Stock Prism JS is
excluded only while its exact bytes match the existing `upstream_unmodified`
manifest. The maintained copy plugin is measured. XSLT is outside these analyzers'
supported languages and remains CC-004, a prerequisite for parent CC-002.

Python counts start at 1 and use Lizard's native decisions: `if`, `elif`, `for`,
`while`, `except`, `finally`, `and`, `or`, conditional expressions and comprehension
branches. This includes Lizard's conservative `finally` increment. Python's AST
independently inventories named functions, methods, async functions and lambdas.
Each lexical body is projected into an isolated callable before Lizard measures
it. Nested callable bodies belong to their own measurements; nested definition
defaults/decorators and class bases belong to the containing evaluation scope.
Own defaults/decorators/annotations are counted in each callable's projection, preserving
header decisions conservatively even when they execute in an enclosing scope.
Formatted-string values and format specifications are exposed as tuple expressions
so Lizard can see their decisions rather than treating them as inert string text.
The projection is parsed, never executed, and its normalized AST hash is recorded
to tolerate Python 3.11/3.12 unparse quoting differences. Original callable
identities include both AST semantics and exact source text. Calibration covers
nested functions, lambdas/defaults, classes, async, comprehensions, boolean
branches, exception handling, inert string tokens and the threshold of 9.
Structural pattern matching, exception groups and Python 3.12 generic declarations
are rejected explicitly; they are not used in the measured inventory.

JavaScript counts come directly from ESLint's native classic rule, including
default arguments, logical expressions, optional-chain segments, conditional
expressions, loops, catches and switch cases. Installed Acorn independently
inventories lexical functions, methods, class-field initializers and static
blocks. Results must map one-to-one to those regions; unknown, missing, duplicate,
fatal or suppressed results fail. CLI inline configuration is disabled. The
calibration fixture covers regex tokens, nesting, methods, arrows, optional chains,
defaults, implicit class scopes and the threshold of 9. Acorn's ES2022 module
grammar is the admitted syntax; unsupported syntax fails parsing. Analyzer and
parser implementation digests are recorded and checked across measurement.

The policy applies to new/changed functions. `baseline.json` pins exact callable
identities from the preserved pre-policy revision
`d879c1c3b8f5523fc41dc9ebf4e54a2934411ac3`. Five unchanged functions exceed 9:
`articles.parse_article_xml` (10), `PosixPublicationBackend._validate_journal`
(10), `ownership._published_paths` (10), `publication._backend` (12) and
`sections.validate_index_first_pattern` (13). Any edit to those identities removes
their baseline eligibility. This preserves the agreed scope without suppressions.

Eight scoped violations were decomposed without changing their contracts:
slot placement, loose-text eligibility, owned-entry validation, planning input
normalization, output-character validation, native fence admission, taxonomy
provenance fixture setup and output-fault construction. Existing invalid-input,
boundary, ownership, provenance and native-fence regressions remain intact.
`tests/test_complexity_gate.py` adds permanent malformed-input/property and
deliberately faulty-provider controls. The normal pytest coverage gate and
`articulous.coverage_gate` retain their existing thresholds.

All measurement data is owned by one synchronous invocation. ASTs, projections,
source bytes and decoded evidence are temporary owned values; providers borrow
repository paths only while their owned process group is alive. Native commands
use the existing Linux session/fence backend, including its cancellation and
recovery ownership. No callback, open file or borrowed AST escapes into results.
Inputs are the finite caller-funded repository inventory; evidence admission is
bounded at 32 MiB. Files are closed before parsing, source identities are checked
after measurement, and report publication uses the existing atomic writer.
Failure leaves prior published evidence intact; no retained native resource is
released based solely on a JSON result. Native backend validation remains Linux.
