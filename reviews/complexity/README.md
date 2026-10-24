# Offline complexity acceptance

CC-003 uses installed Lizard 1.23.0 for Python and cached ESLint 10.8.1
(`complexity`, classic variant) for JavaScript. No package installation, network
access or modification of the cached analyzers is required.

From the repository root:

```sh
export ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn
.venv/bin/python -m articulous.complexity_gate measure \
  --python-analyzer /usr/bin/python3 \
  --eslint /home/netto/.npm/_npx/515228b7c8d004a2/node_modules/eslint
.venv/bin/python -m articulous.complexity_gate check
```

`functions.json` is the schema-2 aggregate: `python_javascript` contains the
schema-1 callable inventory, and `xslt` contains its independent schema-1
per-template report. Both components record source identities, analyzer versions
and calibration. Both must validate before the aggregate is atomically published.
Missing, invalid or stale components fail the whole check; the Python/JavaScript
component alone cannot satisfy aggregate acceptance. There is no legacy fallback.
The check validates a trusted snapshot without rerunning complexity analyzers or
authenticating an edited report. It independently parses JavaScript with installed
Acorn 8.17.0, compares the complete multiset of callable kinds, UTF-16 source
boundaries and body/projection hashes, and rejects changes during parsing.
Missing, extra and mismatched JavaScript functions fail even when the enclosing
file hash still matches. Record ordering is immaterial. Remeasure after source edits. `xslt.json` remains
the standalone XSLT workflow's snapshot; the aggregate embeds its own measured
XSLT component. CI runs the aggregate check using installed test dependencies;
it does not install Lizard or ESLint to check committed evidence. The manual CI
workflow explicitly installs the lockfile-pinned Acorn verification dependency;
local checks reuse the installed parser selected by `ARTICULOUS_ACORN` and perform
no installation or network transfer. Parser workers borrow persistent source files
through owned process settlement; parsed trees are released after each file check.

The inventory includes root Python entry points, all Python files under
`articulous` and `tests`, and maintained JS/MJS in those trees. Stock Prism JS is
excluded only while its exact bytes match the existing `upstream_unmodified`
manifest. The maintained copy plugin is measured. The separate
[XSLT workflow](xslt.md) uses the installed native XPath compiler and an independent
control-flow contract. Python/JavaScript analyzers do not measure XSLT.

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

CC-002's aggregate contract composes the two independent metric workflows.
Permanent controls reject missing/unknown components, wrong schemas, a stale
XSLT source while Python/JavaScript stay current, and a failed XSLT measurement
before publication. The normal quality workflow invokes aggregate acceptance
after pytest and individual-function coverage. Runtime evidence is separate:
the exact SaxonC-HE 12.10 integration run passed all 16 unchanged tests on Linux
x86_64; see [native acceptance evidence](../saxonc/README.md).
